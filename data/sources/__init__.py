"""SOURCES: where the data comes from, and how a page is fetched once.

One module per source, and the one part of the pipeline the scraping types
share (proprietary fetches nothing - its input is authored in the repo). A
source is a source whatever a type makes of what it says: the wiki is read for
ability numbers by the authoritative type and for playstyles by the heuristic
one, and there is no reason for two clients. So sources sit above the types,
and each type begins at extract.

    cached_get       one page, from the cache if it is there and fresh
    set_max_age      the freshness policy: None keeps a page forever (a build
                     from the caches), 0 refetches every page (the daily
                     refresh); a page that fails to refetch keeps its cached
                     copy, so a flaky source degrades to yesterday's numbers
                     instead of an empty table
    blizzard         the official site
    wiki             the MediaWiki endpoint, which returns JSON and rate-limits
    counterpick      counterpick.gg, fixed to competitive on console

Each module also declares the `sources` row its pages become - code, name and
URL - so provenance lives with the source rather than in a list somewhere else.

Fetching yields raw markup. Pulling data out of it is extract.
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
