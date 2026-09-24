"""The daily refresh: the database and the strategies mirror brought up to
date on a schedule.

    python -m db.refresh              run daily at COUNTRIX_REFRESH_AT
                                        (05:00 by default, container time);
                                        refresh right away first if the
                                        cached pages are older than
                                        COUNTRIX_REFRESH_MAX_AGE_HOURS (20)
    python -m db.refresh --now        one refresh, then exit

A refresh comes in two sizes. The DAILY one refetches what moves day to
day - the wiki's seasons (a snapshot is stamped with the season live that
day) and the rates - then re-mirrors the strategies and re-exports db/raw.
The FULL one is `sync_all` with refresh on: every page of every source,
including the hero pages and the wiki articles (kits, synergies, counters)
that only change with a patch; it runs when
the wiki cache is older than COUNTRIX_REFRESH_FULL_DAYS (7). Either
way a page that fails keeps its cached copy, so a flaky source degrades
to yesterday's numbers rather than an empty table. The `refresher`
container runs this loop.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

from db import CACHE_DIRS
from db.mcp import tools

DEFAULT_AT = os.environ.get("COUNTRIX_REFRESH_AT", "05:00")
DEFAULT_MAX_AGE_HOURS = float(os.environ.get("COUNTRIX_REFRESH_MAX_AGE_HOURS", "20"))
DEFAULT_FULL_DAYS = float(os.environ.get("COUNTRIX_REFRESH_FULL_DAYS", "7"))
# What moves between patches. Seasons first: rates stamp their snapshot with
# the season live today. No tool that reads the hero articles: refetching
# them daily would keep the wiki cache young and a full refresh never due.
DAILY = ("pull_seasons", "pull_rates")


def parse_at(text):
    """'05:00' -> (5, 0); anything else is an error worth stopping on."""
    try:
        hour, minute = text.strip().split(":")
        hour, minute = int(hour), int(minute)
    except ValueError:
        raise ValueError("refresh time must be HH:MM, got %r" % text) from None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("refresh time must be HH:MM, got %r" % text)
    return hour, minute


def seconds_until(at, now=None):
    """Seconds from `now` to the next occurrence of the HH:MM in `at`
    (tomorrow's if today's has passed or is now)."""
    hour, minute = parse_at(at)
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def cache_age_hours(cache_dirs=None):
    """Hours since the newest cached page across the sources; None if there
    is no cache at all (a first build)."""
    newest = None
    for path in (cache_dirs or CACHE_DIRS.values()):
        if not os.path.isdir(path):
            continue
        for name in os.listdir(path):
            mtime = os.path.getmtime(os.path.join(path, name))
            newest = mtime if newest is None else max(newest, mtime)
    if newest is None:
        return None
    return (time.time() - newest) / 3600.0


def full_due(full_days=DEFAULT_FULL_DAYS, cache_dirs=None):
    """A full refresh is due when the slow-moving cache (the wiki's) is older
    than `full_days`, or absent. Its age is the median page's: the daily
    refresh refetches a few pages (the Season pages), a full one all of them."""
    ages = []
    for path in (cache_dirs or [CACHE_DIRS["wiki"]]):
        if os.path.isdir(path):
            ages += [time.time() - os.path.getmtime(os.path.join(path, name))
                     for name in os.listdir(path)]
    if not ages:
        return True
    return sorted(ages)[len(ages) // 2] > full_days * 24 * 3600


def refresh_once(ctx, log=print, full=None, full_days=DEFAULT_FULL_DAYS):
    """One refresh -> (ok, text): daily (seasons, rates, strategies, export)
    or full (every source) - decided by full_due() unless `full` is given.
    Never raises; a failure returns (False, the error)."""
    started = time.time()
    try:
        # inside the try: full_due() reads the database, so the decision can
        # fail like the refresh it decides, and the promise above has to hold
        if full is None:
            full = full_due(full_days)
        log("refresh: starting a %s refresh at %s" % (
            "FULL" if full else "daily", datetime.now().strftime("%Y-%m-%d %H:%M")))
        if full:
            text, _ = tools.run_tool(ctx, "sync_all", refresh=True)
        else:
            parts = []
            for name in DAILY:
                parts.append(tools.run_tool(ctx, name, refresh=True)[0].splitlines()[0])
            parts.append(tools.run_tool(ctx, "load_authored")[0].split(";")[0])
            parts.append(tools.run_tool(ctx, "export_csv")[0])
            text = "; ".join(parts)
    except Exception as error:  # noqa: BLE001  # a failed refresh leaves yesterday's data in place
        log("refresh: FAILED after %.0fs: %s: %s"
            % (time.time() - started, type(error).__name__, error))
        return False, str(error)
    log("refresh: done in %.0fs - %s" % (time.time() - started, text))
    return True, text


def run_forever(ctx, at=DEFAULT_AT, max_age_hours=DEFAULT_MAX_AGE_HOURS, log=print,
                sleep=time.sleep):
    parse_at(at)
    age = cache_age_hours()
    if age is None or age > max_age_hours:
        log("refresh: cached pages are %s - refreshing now"
            % ("absent" if age is None else "%.0fh old" % age))
        refresh_once(ctx, log)
    else:
        log("refresh: cached pages are %.0fh old - fresh enough" % age)
    while True:
        wait = seconds_until(at)
        log("refresh: next at %s (in %dh%02dm)" % (at, wait // 3600, (wait % 3600) // 60))
        sleep(wait)
        refresh_once(ctx, log)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", action="store_true", help="refresh once and exit")
    parser.add_argument("--at", default=DEFAULT_AT, help="daily time, HH:MM (default %s)"
                        % DEFAULT_AT)
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS,
                        help="refresh on start when the cache is older than this")
    parser.add_argument("--full", action="store_true",
                        help="with --now: every source, not just the daily set")
    args = parser.parse_args()
    ctx = tools.Context(log=print)      # DATABASE_URL, or the embedded cluster
    if args.now:
        ok, _ = refresh_once(ctx, full=True if args.full else None)
        sys.exit(0 if ok else 1)
    run_forever(ctx, args.at, args.max_age_hours)


if __name__ == "__main__":
    main()
