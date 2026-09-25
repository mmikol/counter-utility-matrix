"""Fetching: the page cache, its freshness and the request loop, shared by
every source.

    cached_get       one page, from the cache if it is there and fresh
    cached           the cache sequence every reader runs through: the fresh
                     copy, else what it produces, else the stale copy
    request          one page asked for under a RequestPolicy and handed to
                     a reader; a failure is retried while attempts remain
    RequestPolicy    a source's attempts, backoff, timeout and pace
    is_stale         whether a cached page is older than the max_age it is
                     given
    cache_key        a request as a file name in the cache
    session          a requests session that identifies this project
    PullContext      what a pull's run() takes beside its connection: the page
                     cache, the session, the log (stderr unless the caller
                     names another - over stdio, stdout is the MCP wire) and
                     the freshness, max_age. None keeps a page forever (a
                     build from the caches), 0 refetches every page (the
                     refresh); a page that fails to refetch keeps its cached
                     copy and is listed in the context's stale, so a flaky
                     source degrades to yesterday's numbers, never to an
                     empty table, and the pull says so

Each source package (blizzard, wiki) names its own endpoints
and its own `sources` row, so provenance lives with the source. Fetching
yields raw markup; reading it is the package's job.
"""

import dataclasses
import os
import random
import re
import sys
import time
from collections.abc import Callable, Mapping

import requests

MAX_BACKOFF = 60.0
SECONDS_PER_HOUR = 3600.0


class FetchError(Exception):
    """A page that could not be had."""


class RateLimitError(FetchError):
    """The source answered, and its answer says to slow down."""


@dataclasses.dataclass(frozen=True)
class RequestPolicy:
    """How a source is asked for a page.

    attempts counts every request, the first included, so 1 means no retry.
    backoff is the first wait after a failure and doubles each attempt, up to
    MAX_BACKOFF. delay is the pause after a page, jittered.

    Attempts are for a source that stalls under load and does not fail
    outright - Blizzard's rates page answers a few hundred sequential
    requests with a 504. A source that needs hundreds of pages raises both
    attempts and backoff: giving up mid-run loses the whole stage, and the
    wait is cheap next to refetching everything.
    """

    attempts: int = 1
    backoff: float = 1.0
    timeout: float = 30
    delay: float = 1.0


USER_AGENT = "countrix/0.1 (personal project; contact via repo)"


def session() -> requests.Session:
    """A requests session that says who we are."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


# Where a progress line goes - a pull's, a tool's, the sentry's: to_stderr
# below, print, a list's append.
type Log = Callable[[str], None]


def to_stderr(line: str) -> None:
    """A progress line on stderr: over stdio, stdout is the MCP wire."""
    sys.stderr.write(line + "\n")


@dataclasses.dataclass(frozen=True)
class PullContext:
    """What a pull runs with: the page cache it reads through (None reads
    none), the session it fetches on, where its progress lines go, and the
    seconds a cached page stays fresh - None keeps a page forever (a build
    from the caches), 0 refetches every page (a refresh).

    stale holds 'name: error' for each page whose refetch failed and whose
    cached copy was read instead. The context stays frozen: only the list's
    contents change."""
    cache_dir: str | None
    session: requests.Session = dataclasses.field(default_factory=session)
    log: Log = to_stderr
    max_age: float | None = None
    stale: list[str] = dataclasses.field(default_factory=list)


def _age(path: str) -> float:
    """Seconds since a cached page was written."""
    return time.time() - os.path.getmtime(path)


def is_stale(path: str, max_age: float | None) -> bool:
    """A cached page older than `max_age` seconds (never, when it is None)."""
    return max_age is not None and _age(path) > max_age


def _read_cache(path: str) -> str:
    """A cached page's text."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _write_cache(path: str, text: str) -> None:
    """A page's text into the cache, over any older copy."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _keep_stale(pull: PullContext, path: str, error: Exception) -> str:
    """A refetch failed: fall back to the cached copy, record it in the pull's
    stale and say so in its log."""
    name = os.path.basename(path)
    pull.stale.append("%s: %s" % (name, error))
    hours = _age(path) / SECONDS_PER_HOUR
    pull.log("warning: %s; keeping the cached copy from %.0fh ago (%s)" % (error, hours, name))
    return _read_cache(path)


def cache_key(*parts: object) -> str:
    """A filesystem-safe name for a request."""
    return re.sub(r"[^A-Za-z0-9]+", "_", "_".join(str(p) for p in parts)).strip("_")


def request[T](
        session: requests.Session, url: str, params: Mapping[str, str] | None,
        policy: RequestPolicy, read: Callable[[requests.Response], T]) -> T:
    """One page asked for under `policy`, and what `read` makes of it.

    A requests failure or a RateLimitError from `read` is retried while attempts
    remain, and raises FetchError when they run out. Any other FetchError
    from `read` is the answer, and is not retried.
    """
    last_error: Exception | None = None
    for attempt in range(policy.attempts):
        try:
            response = session.get(url, params=params, timeout=policy.timeout)
            response.raise_for_status()
            result = read(response)
        except (requests.RequestException, RateLimitError) as error:
            last_error = error
            if attempt + 1 < policy.attempts:     # no point waiting to give up
                # Drop the pooled connections before trying again. A source
                # that answers "Remote end closed connection without response"
                # has hung up on a keep-alive socket, and retrying down the
                # same dead socket fails identically however long we wait.
                session.close()
                time.sleep(min(MAX_BACKOFF, policy.backoff * 2 ** attempt))
        else:
            # Jittered, so a few hundred sequential requests do not arrive as a clock.
            # The jitter is politeness and not a secret, so B311 does not apply.
            time.sleep(policy.delay * random.uniform(0.75, 1.5))  # nosec B311
            return result
    raise FetchError("%s failed after %d attempts: %s" % (url, policy.attempts, last_error))


def cached(pull: PullContext, name: str, produce: Callable[[], str]) -> str:
    """The text of cache file `name` in the pull's cache, fresh from the cache
    or from produce().

    A copy younger than the pull's max_age is read and nothing is asked for.
    Otherwise produce() runs and its text is written. When it fails with a
    FetchError, the stale copy is kept and named in the pull's stale, and
    the failure surfaces only when there is none. Without a cache_dir it only
    produces.
    """
    if not pull.cache_dir:
        return produce()
    path = os.path.join(pull.cache_dir, name)
    if os.path.exists(path) and not is_stale(path, pull.max_age):
        return _read_cache(path)
    try:
        text = produce()
    except FetchError as error:
        if os.path.exists(path):
            return _keep_stale(pull, path, error)
        raise
    _write_cache(path, text)
    return text


def cached_get(
        pull: PullContext, url: str, key: str, params: Mapping[str, str] | None = None, *,
        policy: RequestPolicy) -> str:
    """One page as text, through the pull's page cache as `key`.html."""
    return cached(pull, key + ".html", lambda: request(
        pull.session, url, params, policy, lambda response: response.text))
