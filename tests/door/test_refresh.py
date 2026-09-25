"""The daily refresh's clock: the scheduler's arithmetic, the cache ages
that make a refresh due, the loop, the command line and the tools each
refresh calls. Pure - stubbed tools, no network, no database."""

from datetime import datetime

import pytest

from door import refresh
from door.mcp.schema import ToolReply
from tests.db.test_fetch import write_aged


def test_seconds_until_the_next_daily_run():
    now = datetime(2026, 9, 13, 14, 0, 0)
    assert refresh.seconds_until("05:00", now) == 15 * 3600
    assert refresh.seconds_until("14:30", now) == 30 * 60
    assert refresh.seconds_until("14:00", now) == 24 * 3600      # now counts as passed
    with pytest.raises(ValueError, match="HH:MM"):
        refresh.seconds_until("5pm", now)


def test_cache_age_reads_the_newest_page(tmp_path):
    assert refresh.cache_age_hours([str(tmp_path / "missing")]) is None
    write_aged(tmp_path / "old.html", "x", hours=100)
    write_aged(tmp_path / "newer.html", "x", hours=30)
    assert 29.9 < refresh.cache_age_hours([str(tmp_path)]) < 30.1


def test_refresh_once_survives_a_bad_day(monkeypatch):
    from door.mcp import tools
    logs = []
    nowhere = tools.Context(dsn="postgresql://nowhere", client="test")
    monkeypatch.setattr(tools.Context, "call", lambda ctx, name, **kw: (_ for _ in ()).throw(
        RuntimeError("blizzard 504")))
    ok, text = refresh.refresh_once(nowhere, logs.append)
    assert ok is False and "504" in text and any("FAILED" in line for line in logs)
    traceback = next(line for line in logs if line.startswith("Traceback"))
    assert traceback.endswith("RuntimeError: blizzard 504")
    monkeypatch.setattr(tools.Context, "call",
                        lambda ctx, name, **kw: ToolReply("sync_all: done", {}))
    ok, _ = refresh.refresh_once(nowhere, logs.append)
    assert ok is True


def test_the_loop_refreshes_stale_data_on_start_then_waits(monkeypatch):
    runs, waits = [], []
    monkeypatch.setattr(refresh, "cache_age_hours", lambda *a: 30.0)
    monkeypatch.setattr(refresh, "refresh_once",
                        lambda ctx, log, **kw: runs.append(kw) or (True, ""))

    def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        refresh.run_forever(None, refresh.Schedule("05:00", 20, 7), log=lambda m: None,
                            sleep=sleep)
    assert runs == [{"full_days": 7}] * 2 and all(0 < w <= 24 * 3600 for w in waits)


def test_a_schedule_refuses_a_time_that_is_not_hh_mm():
    with pytest.raises(ValueError, match="HH:MM"):
        refresh.Schedule("5pm", 20, 7)


def test_the_command_line_exits_with_the_refresh_verdict(monkeypatch):
    verdicts = iter([(False, "down"), (True, "")])
    contexts = []
    monkeypatch.setattr(refresh, "refresh_once",
                        lambda ctx, **kw: contexts.append(ctx) or next(verdicts))
    assert refresh.main(["--now"]) == 1
    assert refresh.main(["--now"]) == 0
    assert [ctx.client for ctx in contexts] == ["refresher", "refresher"]   # its audit lines


def test_the_refresh_clock_is_read_from_the_environment_at_start(monkeypatch):
    # tools.Context resolves its dsn lazily, so nothing here touches a database
    schedules, once = [], []
    monkeypatch.setattr(refresh, "run_forever",
                        lambda ctx, schedule: schedules.append(schedule))
    monkeypatch.setattr(refresh, "refresh_once",
                        lambda ctx, **kw: once.append(kw) or (True, ""))
    monkeypatch.setenv("COUNTRIX_REFRESH_AT", "06:30")
    monkeypatch.setenv("COUNTRIX_REFRESH_MAX_AGE_HOURS", "5")
    monkeypatch.setenv("COUNTRIX_REFRESH_FULL_DAYS", "3")
    refresh.main([])
    assert refresh.main(["--now"]) == 0 and once[-1]["full_days"] == 3.0
    for name in ("COUNTRIX_REFRESH_AT", "COUNTRIX_REFRESH_MAX_AGE_HOURS",
                 "COUNTRIX_REFRESH_FULL_DAYS"):
        monkeypatch.delenv(name)
    refresh.main([])
    assert schedules == [refresh.Schedule("06:30", 5.0, 3.0),
                         refresh.Schedule("05:00", 20.0, 7.0)]


def test_full_refresh_is_due_when_the_slow_caches_are_stale(tmp_path):
    assert refresh.full_due(7, [str(tmp_path / "none")]) is True        # nothing cached
    write_aged(tmp_path / "Ana.wikitext", "x", hours=24 * 3)
    assert refresh.full_due(7, [str(tmp_path)]) is False
    write_aged(tmp_path / "Ana.wikitext", "x", hours=24 * 8)
    assert refresh.full_due(7, [str(tmp_path)]) is True
    # the daily refresh refetches the Season pages; the rest still says stale
    write_aged(tmp_path / "Mei.wikitext", "x", hours=24 * 9)
    write_aged(tmp_path / "Season.wikitext", "x", hours=1)
    assert refresh.full_due(7, [str(tmp_path)]) is True
    assert refresh.full_due(7) in (True, False)     # the default reads the wiki cache


def test_daily_refresh_touches_only_what_moves(monkeypatch):
    from door.mcp import tools
    calls = []
    monkeypatch.setattr(tools.Context, "call", lambda ctx, name, **kw: calls.append(
        (name, kw.get("refresh"))) or ToolReply("%s: ok\n  rows  1" % name, {}))
    ok, text = refresh.refresh_once(tools.Context(dsn="postgresql://nowhere", client="test"),
                                    lambda m: None, full=False)
    # seasons first: the day's snapshots are stamped with the season live today
    assert ok and calls == [("pull_seasons", True), ("pull_rates", True),
                            ("load_authored", None), ("export_csv", None)]
    # the log keeps each tool's headline line, not its counts
    assert text == "pull_seasons: ok; pull_rates: ok; load_authored: ok; export_csv: ok"
    # the hero articles (kits, synergies, counters) are the full refresh's: a
    # daily refetch would keep the wiki cache young and full_due() never true
    assert not set(refresh.DAILY) & {"pull_kits", "pull_synergies", "pull_counters"}
    assert "pull_counters" in [spec.name for spec in tools.REGISTRY.pulls()]
    # the calls above are stubbed, so a renamed tool would pass them: the names are checked here
    assert {name for name, _ in calls} <= set(tools.REGISTRY.names())
    calls.clear()
    ok, text = refresh.refresh_once(tools.Context(dsn="postgresql://nowhere", client="test"),
                                    lambda m: None, full=True)
    assert ok and calls == [("sync_all", True)] and text == "sync_all: ok"
    assert {name for name, _ in calls} <= set(tools.REGISTRY.names())
