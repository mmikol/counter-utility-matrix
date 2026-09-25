"""The daily refresh: the database and the strategies mirror brought up to
date on a schedule.

    python -m door.refresh              run daily at COUNTRIX_REFRESH_AT
                                        (05:00 by default, container time);
                                        refresh right away first if the
                                        cached pages are older than
                                        COUNTRIX_REFRESH_MAX_AGE_HOURS (20)
    python -m door.refresh --now        one refresh, then exit 0, or 1 if it fails

A refresh comes in two sizes. The DAILY one refetches what moves day to
day - the wiki's seasons (a snapshot is stamped with the season live that
day) and the rates - then re-mirrors the strategies and re-exports db/raw.
The FULL one is `sync_all` with refresh on: every page of every source,
including the hero pages and the wiki articles (kits, synergies, counters)
that only change with a patch; it runs when
the wiki cache is older than COUNTRIX_REFRESH_FULL_DAYS (7). Either
way a page that fails keeps its cached copy, so a flaky source degrades
to yesterday's numbers rather than an empty table, and the pull's reply
lists it under stale: its first line, which the log keeps, ends with the
count, and sync_all's with the pulls that read one. The `refresher`
container runs this loop.
"""

import argparse
import os
import statistics
import time
import traceback
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NamedTuple, NoReturn

from db import CACHE_DIRS
from db.data.fetch import SECONDS_PER_HOUR
from door.mcp import tools

# The clock when the environment names none: COUNTRIX_REFRESH_AT,
# COUNTRIX_REFRESH_MAX_AGE_HOURS and COUNTRIX_REFRESH_FULL_DAYS, read by main()
DEFAULT_AT = "05:00"
DEFAULT_MAX_AGE_HOURS = 20.0
DEFAULT_FULL_DAYS = 7.0
# What moves between patches. Seasons first: rates stamp their snapshot with
# the season live today. No tool that reads the hero articles: refetching
# them daily would keep the wiki cache young and a full refresh never due.
DAILY = ("pull_seasons", "pull_rates")


def parse_at(text: str) -> tuple[int, int]:
    """'05:00' -> (5, 0); anything else is an error worth stopping on."""
    try:
        hours, minutes = text.strip().split(":")
        hour, minute = int(hours), int(minutes)
    except ValueError:
        raise ValueError("refresh time must be HH:MM, got %r" % text) from None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("refresh time must be HH:MM, got %r" % text)
    return hour, minute


@dataclass(frozen=True)
class Schedule:
    """When the loop refreshes: daily at `at` (HH:MM), at once on start when
    the cache is older than `max_age_hours`, and in full when the wiki cache
    is older than `full_days`. A time that is not HH:MM refuses here, before
    the loop starts."""
    at: str
    max_age_hours: float
    full_days: float

    def __post_init__(self) -> None:
        parse_at(self.at)


def seconds_until(at: str, now: datetime | None = None) -> float:
    """Seconds from `now` to the next occurrence of the HH:MM in `at`
    (tomorrow's if today's has passed or is now)."""
    hour, minute = parse_at(at)
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _page_ages(cache_dirs: Iterable[str]) -> list[float]:
    """Seconds since each cached page in `cache_dirs` was written; a directory
    that does not exist holds none."""
    now = time.time()
    return [now - os.path.getmtime(os.path.join(path, name))
            for path in cache_dirs if os.path.isdir(path) for name in os.listdir(path)]


def cache_age_hours(cache_dirs: Iterable[str] | None = None) -> float | None:
    """Hours since the newest cached page across the sources; None if there
    is no cache at all (a first build)."""
    ages = _page_ages(cache_dirs or CACHE_DIRS.values())
    return min(ages) / SECONDS_PER_HOUR if ages else None


def full_due(
        full_days: float = DEFAULT_FULL_DAYS, cache_dirs: Iterable[str] | None = None) -> bool:
    """A full refresh is due when the slow-moving cache (the wiki's) is older
    than `full_days`, or absent. Its age is the median page's: the daily
    refresh refetches a few pages (the Season pages), a full one all of them."""
    ages = _page_ages(cache_dirs or [CACHE_DIRS["wiki"]])
    if not ages:
        return True
    return statistics.median_high(ages) > full_days * 24 * SECONDS_PER_HOUR


class Refreshed(NamedTuple):
    """What one refresh came to: whether it succeeded, and its summary or its
    error."""
    ok: bool
    text: str


def refresh_once(
        ctx: tools.Context, log: tools.Log = print, full: bool | None = None,
        full_days: float = DEFAULT_FULL_DAYS) -> Refreshed:
    """One refresh -> (ok, text): daily (seasons, rates, strategies, export)
    or full (every source) - decided by full_due() unless `full` is given -
    its text each tool's headline, joined by "; ". Never raises; a failure
    returns (False, the error)."""
    started = time.time()
    try:
        # inside the try: full_due() lists and stats the page cache, which can
        # raise OSError like the refresh it decides, and the promise above has to hold
        if full is None:
            full = full_due(full_days)
        log("refresh: starting a %s refresh at %s" % (
            "FULL" if full else "daily", datetime.now().strftime("%Y-%m-%d %H:%M")))
        if full:
            calls: list[tuple[str, dict[str, object]]] = [("sync_all", {"refresh": True})]
        else:
            calls = [(name, {"refresh": True}) for name in DAILY]
            calls += [("load_authored", {}), ("export_csv", {})]
        text = "; ".join(ctx.call(name, **arguments).text.partition("\n")[0]
                         for name, arguments in calls)
    except Exception as error:  # noqa: BLE001  # a failed refresh leaves yesterday's data in place
        log(traceback.format_exc().rstrip())
        log("refresh: FAILED after %.0fs: %s: %s"
            % (time.time() - started, type(error).__name__, error))
        return Refreshed(False, str(error))
    log("refresh: done in %.0fs - %s" % (time.time() - started, text))
    return Refreshed(True, text)


def run_forever(
        ctx: tools.Context, schedule: Schedule, log: tools.Log = print,
        sleep: Callable[[float], object] = time.sleep) -> NoReturn:
    """Refresh at once if the cache is stale, then daily at the schedule's time."""
    age = cache_age_hours()
    if age is None or age > schedule.max_age_hours:
        log("refresh: cached pages are %s - refreshing now"
            % ("absent" if age is None else "%.0fh old" % age))
        refresh_once(ctx, log, full_days=schedule.full_days)
    else:
        log("refresh: cached pages are %.0fh old - fresh enough" % age)
    while True:
        wait = seconds_until(schedule.at)
        log("refresh: next at %s (in %dh%02dm)" % (
            schedule.at, wait // SECONDS_PER_HOUR, (wait % SECONDS_PER_HOUR) // 60))
        sleep(wait)
        refresh_once(ctx, log, full_days=schedule.full_days)


def main(argv: list[str] | None = None) -> int:
    """The command line -> its exit code: --now is 0 when the refresh
    succeeds and 1 when it fails; the loop never returns."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", action="store_true", help="refresh once and exit")
    parser.add_argument("--at", default=os.environ.get("COUNTRIX_REFRESH_AT", DEFAULT_AT),
                        help="daily time, HH:MM (default %(default)s)")
    parser.add_argument("--max-age-hours", type=float,
                        default=float(os.environ.get("COUNTRIX_REFRESH_MAX_AGE_HOURS",
                                                     DEFAULT_MAX_AGE_HOURS)),
                        help="refresh on start when the cache is older than this")
    parser.add_argument("--full", action="store_true",
                        help="with --now: every source, not just the daily set")
    args = parser.parse_args(argv)
    # the full-refresh age has no flag: nothing passes one, and compose sets it
    full_days = float(os.environ.get("COUNTRIX_REFRESH_FULL_DAYS", DEFAULT_FULL_DAYS))
    ctx = tools.Context(log=print, client="refresher")  # DATABASE_URL, or the embedded cluster
    if args.now:
        ok, _ = refresh_once(ctx, full=args.full or None, full_days=full_days)
        return 0 if ok else 1
    run_forever(ctx, Schedule(at=args.at, max_age_hours=args.max_age_hours,
                              full_days=full_days))


if __name__ == "__main__":
    raise SystemExit(main())
