"""The daily refresh: the cache policy (refetch by age, keep the old page
when the source fails) and the scheduler's arithmetic. Pure - fake sessions,
no network, no database."""

import os
import time
from datetime import datetime

import pytest
import requests

from data import refresh, sources
from data.sources import wiki


class FakeResponse:
    def __init__(self, text, payload=None):
        self.text, self._payload = text, payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    """Answers with `text`, or raises when `fail` is set."""

    def __init__(self, text="new page", fail=False, payload=None):
        self.text, self.fail, self.payload, self.calls = text, fail, payload, 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.fail:
            raise requests.ConnectionError("source down")
        return FakeResponse(self.text, self.payload)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def forever_after():
    yield
    sources.set_max_age(None)          # never leak a policy into other tests


def _old_file(path, text, hours=48):
    path.write_text(text, encoding="utf-8")
    stamp = time.time() - hours * 3600
    os.utime(str(path), (stamp, stamp))


def test_a_fresh_cache_is_read_without_fetching(tmp_path):
    _old_file(tmp_path / "k.html", "cached")
    session = FakeSession()
    assert sources.cached_get(session, "u", str(tmp_path), "k", delay=0) == "cached"
    assert session.calls == 0


def test_refresh_refetches_a_stale_page_and_rewrites_the_cache(tmp_path):
    _old_file(tmp_path / "k.html", "cached")
    sources.set_max_age(0)
    session = FakeSession("new page")
    assert sources.cached_get(session, "u", str(tmp_path), "k", delay=0) == "new page"
    assert session.calls == 1
    assert (tmp_path / "k.html").read_text(encoding="utf-8") == "new page"
    # the rewritten page is fresh under any finite policy but the refresh one
    sources.set_max_age(3600)
    assert not sources.is_stale(str(tmp_path / "k.html"))
    sources.set_max_age(None)
    assert not sources.is_stale(str(tmp_path / "k.html"))


def test_a_failed_refetch_keeps_the_cached_copy(tmp_path, capsys):
    _old_file(tmp_path / "k.html", "yesterday")
    sources.set_max_age(0)
    session = FakeSession(fail=True)
    assert sources.cached_get(session, "u", str(tmp_path), "k", delay=0,
                              retries=2, backoff=0) == "yesterday"
    assert "keeping the cached copy" in capsys.readouterr().err
    with pytest.raises(sources.FetchError):     # nothing cached: the failure surfaces
        sources.cached_get(FakeSession(fail=True), "u", str(tmp_path), "other",
                           delay=0, backoff=0)


def test_wiki_cargo_and_wikitext_keep_stale_copies_too(tmp_path):
    _old_file(tmp_path / "cargo_abilities.json", '[{"a": 1}]')
    _old_file(tmp_path / "Ana.wikitext", "{{Infobox}}")
    sources.set_max_age(0)
    down = FakeSession(fail=True)
    assert wiki.cargo_query(down, "Abilities", ("a",), str(tmp_path)) == [{"a": 1}]
    assert wiki.fetch_wikitext(down, "Ana", str(tmp_path)) == "{{Infobox}}"
    up = FakeSession(payload={"cargoquery": [{"title": {"a": 2}}]})
    assert wiki.cargo_query(up, "Abilities", ("a",), str(tmp_path)) == [{"a": 2}]


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
    from data.mcp import tools
    logs = []
    monkeypatch.setattr(tools, "run_tool", lambda ctx, name, **kw: (_ for _ in ()).throw(
        RuntimeError("blizzard 504")))
    ok, text = refresh.refresh_once(tools.Context(dsn="postgresql://nowhere"), logs.append)
    assert ok is False and "504" in text and any("FAILED" in l for l in logs)
    monkeypatch.setattr(tools, "run_tool", lambda ctx, name, **kw: ("sync_all: done", {}))
    ok, _ = refresh.refresh_once(tools.Context(dsn="postgresql://nowhere"), logs.append)
    assert ok is True


def test_the_loop_refreshes_stale_data_on_start_then_waits(monkeypatch):
    runs, waits = [], []
    monkeypatch.setattr(refresh, "cache_age_hours", lambda *a: 30.0)
    monkeypatch.setattr(refresh, "refresh_once", lambda ctx, log: runs.append(1) or (True, ""))

    def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        refresh.run_forever(None, "05:00", 20, log=lambda m: None, sleep=sleep)
    assert runs == [1, 1] and all(0 < w <= 24 * 3600 for w in waits)
