"""The page cache in db/data/fetch.py and the wiki's requests through it:
refetch by age, keep the old page when the source fails, retry a rate
limit, ask for an article once. Pure - fake sessions, no network, no
database."""

import os
import threading
import time

import pytest
import requests

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


def write_aged(path, text, hours=48):
    """Write a cached page whose modification time is `hours` old."""
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
    write_aged(tmp_path / "k.html", "cached")
    session = FakeSession()
    assert fetch.cached_get(session, "u", str(tmp_path), "k", policy=INSTANT) == "cached"
    assert session.calls == 0


def test_refresh_refetches_a_stale_page_and_rewrites_the_cache(tmp_path):
    write_aged(tmp_path / "k.html", "cached")
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
    write_aged(tmp_path / "k.html", "yesterday")
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
    write_aged(tmp_path / "cargo_abilities.json", '[{"a": "1"}]')
    write_aged(tmp_path / "Ana.wikitext", "{{Infobox}}")
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
    write_aged(cached / "Ana.wikitext", "{{Infobox}}")
    write_aged(cached / "cargo_abilities.json", '[{"a": "1"}]')
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
