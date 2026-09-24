"""The daily refresh: the cache policy (refetch by age, keep the old page
when the source fails) and the scheduler's arithmetic. Pure - fake sessions,
no network, no database."""

import os
import threading
import time
from datetime import datetime

import pytest
import requests

from db import refresh
from db.data import fetch, wiki

INSTANT = fetch.RequestPolicy(backoff=0, delay=0)


class FakeResponse:
    def __init__(self, text="", payload=None, status=200):
        self.text, self._payload, self.status = text, payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError("%d" % self.status, response=self)

    def json(self):
        return self._payload


class FakeSession:
    """Answers with `text`, or raises when `fail` is set; with `answers`, hands
    them out one per request."""

    def __init__(self, text="new page", fail=False, payload=None, answers=None):
        self.text, self.fail, self.payload, self.calls = text, fail, payload, 0
        self.answers = list(answers or [])

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.fail:
            raise requests.ConnectionError("source down")
        if self.answers:
            return self.answers.pop(0)
        return FakeResponse(self.text, self.payload)

    def close(self):
        pass


def _old_file(path, text, hours=48):
    path.write_text(text, encoding="utf-8")
    stamp = time.time() - hours * 3600
    os.utime(str(path), (stamp, stamp))


def test_the_freshness_policy_is_per_thread_and_a_block_restores_it():
    """The door serves calls on threads, so one caller's refresh must not decide
    another caller's pull; and max_age() puts back whatever it found."""
    seen = {}
    with fetch.max_age(0):
        thread = threading.Thread(target=lambda: seen.setdefault("age", fetch._max_age()))
        thread.start()
        thread.join()
        assert seen["age"] is None and fetch._max_age() == 0
        with fetch.max_age(3600):
            assert fetch._max_age() == 3600
        assert fetch._max_age() == 0
        with pytest.raises(RuntimeError), fetch.max_age(7):
            raise RuntimeError("the block leaves by the other door")
        assert fetch._max_age() == 0
    assert fetch._max_age() is None


def test_a_fresh_cache_is_read_without_fetching(tmp_path):
    _old_file(tmp_path / "k.html", "cached")
    session = FakeSession()
    assert fetch.cached_get(session, "u", str(tmp_path), "k", policy=INSTANT) == "cached"
    assert session.calls == 0


def test_refresh_refetches_a_stale_page_and_rewrites_the_cache(tmp_path):
    _old_file(tmp_path / "k.html", "cached")
    session = FakeSession("new page")
    with fetch.max_age(0):
        assert fetch.cached_get(session, "u", str(tmp_path), "k", policy=INSTANT) == "new page"
        assert session.calls == 1
        assert (tmp_path / "k.html").read_text(encoding="utf-8") == "new page"
    # the rewritten page is fresh under any finite policy but the refresh one
    with fetch.max_age(3600):
        assert not fetch.is_stale(str(tmp_path / "k.html"))
    assert not fetch.is_stale(str(tmp_path / "k.html"))


def test_a_failed_refetch_keeps_the_cached_copy(tmp_path, capsys):
    _old_file(tmp_path / "k.html", "yesterday")
    session = FakeSession(fail=True)
    twice = fetch.RequestPolicy(attempts=2, backoff=0, delay=0)
    with fetch.max_age(0):
        assert fetch.cached_get(session, "u", str(tmp_path), "k", policy=twice) == "yesterday"
        assert "keeping the cached copy" in capsys.readouterr().err
        with pytest.raises(fetch.FetchError):     # nothing cached: the failure surfaces
            fetch.cached_get(FakeSession(fail=True), "u", str(tmp_path), "other",
                             policy=INSTANT)


def test_attempts_count_every_request_the_first_included():
    session = FakeSession(fail=True)
    with pytest.raises(fetch.FetchError, match="after 3 attempts"):
        fetch.cached_get(session, "u", None, "k",
                         policy=fetch.RequestPolicy(attempts=3, backoff=0, delay=0))
    assert session.calls == 3


def test_wiki_cargo_and_wikitext_keep_stale_copies_too(tmp_path, instant_wiki):
    _old_file(tmp_path / "cargo_abilities.json", '[{"a": "1"}]')
    _old_file(tmp_path / "Ana.wikitext", "{{Infobox}}")
    down = FakeSession(fail=True)
    up = FakeSession(payload={"cargoquery": [{"title": {"a": "2"}}]})
    with fetch.max_age(0):
        assert wiki.cargo_query(down, "Abilities", ("a",), str(tmp_path)) == [{"a": "1"}]
        assert wiki.fetch_wikitext(down, "Ana", str(tmp_path)) == "{{Infobox}}"
        assert wiki.cargo_query(up, "Abilities", ("a",), str(tmp_path)) == [{"a": "2"}]


def test_a_changed_wiki_response_shape_keeps_the_stale_copy(tmp_path, instant_wiki):
    """A 200 whose JSON lost the keys it should carry is a failure like any
    other: the stale copy serves, and with none cached it surfaces as WikiError."""
    cached, empty = tmp_path / "cached", tmp_path / "empty"
    cached.mkdir()
    empty.mkdir()
    _old_file(cached / "Ana.wikitext", "{{Infobox}}")
    _old_file(cached / "cargo_abilities.json", '[{"a": "1"}]')
    no_wikitext = FakeSession(payload={"parse": {}})
    no_title = FakeSession(payload={"cargoquery": [{"row": {}}]})
    with fetch.max_age(0):
        assert wiki.fetch_wikitext(no_wikitext, "Ana", str(cached)) == "{{Infobox}}"
        assert wiki.cargo_query(no_title, "Abilities", ("a",), str(cached)) == [{"a": "1"}]
        with pytest.raises(wiki.WikiError, match="no wikitext"):
            wiki.fetch_wikitext(no_wikitext, "Ana", str(empty))
        with pytest.raises(wiki.WikiError, match="a row has no title"):
            wiki.cargo_query(no_title, "Abilities", ("a",), str(empty))


CARGO_PAGE = {"cargoquery": [{"title": {"a": "1"}}]}


def test_the_wiki_retries_a_429_and_reads_the_next_answer(instant_wiki):
    session = FakeSession(answers=[FakeResponse(status=429), FakeResponse(payload=CARGO_PAGE)])
    assert wiki.cargo_query(session, "T", ["a"], None) == [{"a": "1"}]
    assert session.calls == 2


def test_a_rate_limit_stated_in_the_body_is_retried(instant_wiki):
    limited = FakeResponse(payload={"error": {"info": "Rate limit exceeded"}})
    session = FakeSession(answers=[limited, FakeResponse(payload=CARGO_PAGE)])
    assert wiki.cargo_query(session, "T", ["a"], None) == [{"a": "1"}]
    assert session.calls == 2


def test_an_article_that_fails_is_asked_for_once(instant_wiki):
    session = FakeSession(fail=True)
    with pytest.raises(fetch.FetchError):
        wiki.fetch_wikitext(session, "Ana", None)
    assert session.calls == 1


def test_an_article_that_will_not_fetch_is_recorded_and_the_rest_are_read(tmp_path, instant_wiki):
    # the title goes to the cache as it is: its name folds spaces and punctuation
    (tmp_path / "King_s_Row.wikitext").write_text("{{Infobox map}}", encoding="utf-8")
    session, logged = FakeSession(fail=True), []
    articles = wiki.fetch_articles(session, ["King's Row", "Hanaoka"], str(tmp_path),
                                   logged.append)
    assert articles.found == {"King's Row": "{{Infobox map}}"}
    [line] = articles.missing
    assert line.startswith("Hanaoka: ") and "source down" in line
    assert session.calls == 1                       # the uncached one, asked for once
    assert logged == ["  %-22s %s" % ("Hanaoka", line[len("Hanaoka: "):])]


def test_seconds_until_the_next_daily_run():
    now = datetime(2026, 9, 13, 14, 0, 0)
    assert refresh.seconds_until("05:00", now) == 15 * 3600
    assert refresh.seconds_until("14:30", now) == 30 * 60
    assert refresh.seconds_until("14:00", now) == 24 * 3600      # now counts as passed
    with pytest.raises(ValueError, match="HH:MM"):
        refresh.seconds_until("5pm", now)


def test_cache_age_reads_the_newest_page(tmp_path):
    assert refresh.cache_age_hours([str(tmp_path / "missing")]) is None
    _old_file(tmp_path / "old.html", "x", hours=100)
    _old_file(tmp_path / "newer.html", "x", hours=30)
    assert 29.9 < refresh.cache_age_hours([str(tmp_path)]) < 30.1


def test_refresh_once_survives_a_bad_day(monkeypatch):
    from db.mcp import tools
    logs = []
    monkeypatch.setattr(tools, "run_tool", lambda ctx, name, **kw: (_ for _ in ()).throw(
        RuntimeError("blizzard 504")))
    ok, text = refresh.refresh_once(tools.Context(dsn="postgresql://nowhere"), logs.append)
    assert ok is False and "504" in text and any("FAILED" in line for line in logs)
    traceback = next(line for line in logs if line.startswith("Traceback"))
    assert traceback.endswith("RuntimeError: blizzard 504")
    monkeypatch.setattr(tools, "run_tool", lambda ctx, name, **kw: ("sync_all: done", {}))
    ok, _ = refresh.refresh_once(tools.Context(dsn="postgresql://nowhere"), logs.append)
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
    monkeypatch.setattr(refresh, "refresh_once", lambda ctx, **kw: next(verdicts))
    assert refresh.main(["--now"]) == 1
    assert refresh.main(["--now"]) == 0


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
    _old_file(tmp_path / "Ana.wikitext", "x", hours=24 * 3)
    assert refresh.full_due(7, [str(tmp_path)]) is False
    _old_file(tmp_path / "Ana.wikitext", "x", hours=24 * 8)
    assert refresh.full_due(7, [str(tmp_path)]) is True
    # the daily refresh refetches the Season pages; the rest still says stale
    _old_file(tmp_path / "Mei.wikitext", "x", hours=24 * 9)
    _old_file(tmp_path / "Season.wikitext", "x", hours=1)
    assert refresh.full_due(7, [str(tmp_path)]) is True
    assert refresh.full_due(7) in (True, False)     # the default reads the wiki cache


def test_daily_refresh_touches_only_what_moves(monkeypatch):
    from db.mcp import tools
    calls = []
    monkeypatch.setattr(tools, "run_tool", lambda ctx, name, **kw: calls.append(
        (name, kw.get("refresh"))) or ("%s: ok" % name, {}))
    ok, _ = refresh.refresh_once(tools.Context(dsn="postgresql://nowhere"),
                                 lambda m: None, full=False)
    # seasons first: the day's snapshots are stamped with the season live today
    assert ok and calls == [("pull_seasons", True), ("pull_rates", True),
                            ("load_authored", None), ("export_csv", None)]
    # the hero articles (kits, synergies, counters) are the full refresh's: a
    # daily refetch would keep the wiki cache young and full_due() never true
    assert not set(refresh.DAILY) & {"pull_kits", "pull_synergies", "pull_counters"}
    assert "pull_counters" in [spec.name for spec in tools.REGISTRY.pulls()]
    # the calls above are stubbed, so a renamed tool would pass them: the names are checked here
    assert {name for name, _ in calls} <= set(tools.REGISTRY.names())
    calls.clear()
    ok, _ = refresh.refresh_once(tools.Context(dsn="postgresql://nowhere"),
                                 lambda m: None, full=True)
    assert ok and calls == [("sync_all", True)]
    assert {name for name, _ in calls} <= set(tools.REGISTRY.names())
