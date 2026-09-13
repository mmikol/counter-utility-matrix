"""The daily refresh: the database, the playbook and the heuristics mirror
brought up to date on a schedule, so the board is ready when a game starts.

    python -m data.refresh              run daily at OVERWATCH_DB_REFRESH_AT
                                        (05:00 by default, container time);
                                        refresh right away first if the
                                        cached pages are older than
                                        OVERWATCH_DB_REFRESH_MAX_AGE_HOURS (20)
    python -m data.refresh --now        one refresh, then exit

One refresh is `sync_all` with refresh on: every page of every source is
fetched again (a page that fails keeps its cached copy, so a flaky source
degrades to yesterday's numbers rather than an empty table), entities are
upserted in place, the rates append a new dated snapshot, the authored
playbook and the heuristics files are re-mirrored, and data/raw is
re-exported. The `refresher` container runs this loop.
"""

import os
import sys
import time
from datetime import datetime, timedelta

from data import common
from data.mcp import tools

DEFAULT_AT = os.environ.get("OVERWATCH_DB_REFRESH_AT", "05:00")
DEFAULT_MAX_AGE_HOURS = float(os.environ.get("OVERWATCH_DB_REFRESH_MAX_AGE_HOURS", "20"))


def parse_at(text):
    """'05:00' -> (5, 0); anything else is an error worth stopping on."""
    try:
        hour, minute = text.strip().split(":")
        hour, minute = int(hour), int(minute)
    except ValueError:
        raise ValueError("refresh time must be HH:MM, got %r" % text)
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
    for path in (cache_dirs or common.CACHE_DIRS.values()):
        if not os.path.isdir(path):
            continue
        for name in os.listdir(path):
            mtime = os.path.getmtime(os.path.join(path, name))
            newest = mtime if newest is None else max(newest, mtime)
    if newest is None:
        return None
    return (time.time() - newest) / 3600.0


def refresh_once(ctx, log=print):
    """One full refresh -> (ok, text). Never raises: the loop must survive
    a bad day at the sources."""
    started = time.time()
    log("refresh: starting at %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    try:
        text, _ = tools.run_tool(ctx, "sync_all", refresh=True)
    except Exception as error:      # a failed refresh leaves yesterday's data in place
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
    parser = common.build_parser(__doc__)
    parser.add_argument("--now", action="store_true", help="refresh once and exit")
    parser.add_argument("--at", default=DEFAULT_AT, help="daily time, HH:MM (default %s)"
                        % DEFAULT_AT)
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS,
                        help="refresh on start when the cache is older than this")
    args = parser.parse_args()
    ctx = tools.Context(dsn=common.resolve_dsn(args), log=print)
    if args.now:
        ok, _ = refresh_once(ctx)
        sys.exit(0 if ok else 1)
    run_forever(ctx, args.at, args.max_age_hours)


if __name__ == "__main__":
    main()
