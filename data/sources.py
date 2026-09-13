"""The fetch cache and its freshness policy - shared by every source.

    cached_get       one page, from the cache if it is there and fresh
    set_max_age      the policy: None keeps a page forever (a build from
                     the caches), 0 refetches every page (the refresh); a
                     page that fails to refetch keeps its cached copy, so
                     a flaky source degrades to yesterday's numbers rather
                     than an empty table
    AUTHORED         the `sources` row for the inputs we write instead of
                     fetch (data/authored/); the code stays `user` for
                     continuity with databases built before the rename

    session          a requests session that identifies this project
    PLATFORM, INPUT_DEVICE, REGION
                     the project's scope - console, controller, Americas -
                     declared once; every rates snapshot carries it

Each source package (blizzard, wiki, counterpick) names its own endpoints
and its own `sources` row, so provenance lives with the source. Fetching
yields raw markup; reading it is the package's job.
"""

import os
import random
import re
import sys
import time
import requests

DEFAULT_DELAY = 1.0
DEFAULT_TIMEOUT = 30
DEFAULT_BACKOFF = 1.0
MAX_BACKOFF = 60.0

# Seconds a cached page stays fresh; None means forever.
MAX_AGE = None


class FetchError(Exception):
    pass


def set_max_age(seconds):
    """The freshness policy for every fetch that follows (None = forever)."""
    global MAX_AGE
    MAX_AGE = seconds


def is_stale(path):
    """A cached page older than the policy allows (never, when MAX_AGE is None)."""
    if MAX_AGE is None or not path or not os.path.exists(path):
        return False
    return time.time() - os.path.getmtime(path) > MAX_AGE


def read_cache(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write_cache(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def keep_stale(path, error):
    """A refetch failed: fall back to the cached copy, saying so."""
    age = (time.time() - os.path.getmtime(path)) / 3600.0
    sys.stderr.write("warning: %s; keeping the cached copy from %.0fh ago (%s)\n"
                     % (error, age, os.path.basename(path)))
    return read_cache(path)


def cache_key(*parts):
    """A filesystem-safe name for a request."""
    return re.sub(r"[^A-Za-z0-9]+", "_", "_".join(str(p) for p in parts)).strip("_")


def cached_get(session, url, cache_dir, key, params=None, suffix=".html",
               timeout=DEFAULT_TIMEOUT, retries=1, delay=DEFAULT_DELAY,
               backoff=DEFAULT_BACKOFF):
    """Fetch one page as text, reading and writing a local cache.

    retries applies to a source that stalls under load rather than failing
    outright - Blizzard's rates page answers a few hundred sequential requests
    with a 504 - and waits `backoff` seconds, doubling each attempt, before
    trying again. A source that needs hundreds of pages should raise both:
    giving up mid-run loses the whole stage, and the delay is cheap next to
    refetching everything.
    """
    path = os.path.join(cache_dir, key + suffix) if cache_dir else None
    if path and os.path.exists(path) and not is_stale(path):
        return read_cache(path)

    text, last_error = None, None
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            text = response.text
            break
        except requests.RequestException as error:
            last_error = error
            if attempt + 1 < retries:            # no point waiting to give up
                # Drop the pooled connections before trying again. A source
                # that answers "Remote end closed connection without response"
                # has hung up on a keep-alive socket, and retrying down the
                # same dead socket fails identically however long we wait.
                session.close()
                time.sleep(min(MAX_BACKOFF, backoff * (2 ** attempt)))
    if text is None:
        error = FetchError("%s failed after %d attempts: %s" % (url, retries, last_error))
        if path and os.path.exists(path):
            return keep_stale(path, error)
        raise error

    if path:
        write_cache(path, text)
    # Jittered, so a few hundred sequential requests do not arrive as a clock.
    time.sleep(delay * random.uniform(0.75, 1.5))
    return text


USER_AGENT = "overwatch-db/0.1 (personal project; contact via repo)"

# The scope every rates snapshot is pinned to. The sites spell these their
# own way (Blizzard's input=Console, counterpick's platform=console); these
# are the codes the database stores.
PLATFORM = "console"
INPUT_DEVICE = "controller"
REGION = "americas"


def session(existing=None):
    """A requests session (the given one, or a new one) that says who we are."""
    s = existing or requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


# The inputs we write rather than fetch. There is nothing to download - the
# "url" is the directory - but every row they become still names its source.
AUTHORED = ("user", "Hand-authored inputs", "data/authored/")
