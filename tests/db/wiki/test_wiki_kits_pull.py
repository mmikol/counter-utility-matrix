"""The kits pull, db/data/wiki/heroes.py, over a recording connection and
stubbed fetches: an announced hero the Cargo table names is stored from its
article before its kit, a page that will not fetch or names a subrole the
roster lacks is reported and skipped, and run() stores every kit in one
transaction and counts what it read. No database, no network."""

import datetime

from db.data import fetch
from db.data.wiki import Articles, heroes
from db.data.wiki.kits.hero_articles import HeroProfile, Supplement
from tests.db.recording import RecordingConnection, RecordingCursor

ARTICLE = """{{Upcoming}}
{{Infobox character
| name = %s
| role = Support
| sub-role = %s
| health = 250
}}
'''%s''' is set to release on October 6, 2026.
"""
SUBROLES = {("support", "survivor"): [(7, 3)]}


def _subrole(params):
    """The subrole lookup's answer: a row for a subrole on the roster, none else."""
    return SUBROLES.get(params, [])


def _pull(lines):
    return fetch.PullContext(None, log=lines.append)


def test_an_announced_hero_is_stored_from_its_article_and_the_rest_are_reported():
    """Of the articles of the names the roster lacks: Doctrine's is marked
    upcoming and stored; Oddity's names a subrole the roster has not seeded;
    the overview page is no hero."""
    found = {
        "All heroes": "An overview of every hero.",
        "Doctrine": ARTICLE % ("Doctrine", "Survivor", "Doctrine"),
        "Oddity": ARTICLE % ("Oddity", "Warden", "Oddity")}
    lines = []
    cursor = RecordingCursor(reads=[("SELECT s.subrole_id, r.role_id", _subrole)])
    hero_ids = {"anvil": 101}
    stored = heroes._announce_heroes(cursor, _pull(lines), found, hero_ids, 50)
    assert stored == ["Doctrine"]
    assert cursor.written("INSERT INTO heroes") == [
        ("doctrine", "Doctrine", 3, 7, 250, datetime.date(2026, 10, 6), 50)]
    assert hero_ids == {"anvil": 101, "doctrine": 1}         # the id the upsert read back
    assert lines == [
        "announced hero stored: Doctrine (support, survivor, releases 2026-10-06)",
        "announced hero Oddity: subrole support/warden not on the roster yet, skipped"]


def _cargo(hero, ability, kind, **stats):
    """A Cargo row as the wiki returns it, field names with spaces."""
    row = {"hero name": hero, "ability name": ability, "ability type": kind, "removed": ""}
    row.update(stats)
    return row


ROWS = [
    _cargo("Anvil", "Rocket Hammer", "Weapon", damage="100"),
    _cargo("Anvil", "Old Hammer", "Weapon", removed="1"),
    _cargo("Doctrine", "Benediction", "Ability", heal="80"),
    _cargo("All heroes", "Overview", "Ability")]


def test_the_pull_stores_every_kit_in_one_transaction_and_counts_what_it_read(monkeypatch):
    """Anvil is on the roster and Doctrine is announced by its article, so
    both kits are stored; the overview page is skipped by name, and Wraith's
    article would not fetch, so Wraith stays unknown. Only the heroes the
    roster lacks have their articles read for an announcement, and every one
    is read before the first write. The articles add Anvil's pools and three
    stats, and Kite's would not fetch."""
    asked, written = [], []

    def articles(pull, titles):
        asked.append(list(titles))
        written.extend(text for cursor in connection.cursors for text, _ in cursor.statements
                       if not text.startswith("SELECT"))
        return Articles({"All heroes": "An overview of every hero.",
                         "Doctrine": ARTICLE % ("Doctrine", "Survivor", "Doctrine")},
                        ["Wraith: failed after 1 attempt: gone"])

    def supplement(pull, by_hero):
        assert sorted(by_hero) == ["All heroes", "Anvil", "Doctrine", "Wraith"]
        return Supplement({"Anvil": HeroProfile(health=400, shield=0, armor=300)}, 3,
                          ["Kite: gone"])
    rows = [*ROWS, _cargo("Wraith", "Shadow Step", "Ability")]
    monkeypatch.setattr(heroes, "cargo_query", lambda pull, table, fields: rows)
    monkeypatch.setattr(heroes, "fetch_articles", articles)
    monkeypatch.setattr(heroes, "supplement_kits", supplement)
    connection = RecordingConnection(reads=[
        ('SELECT "name", "hero_id" FROM "heroes"', [("Anvil", 1)]),
        ("SELECT s.subrole_id, r.role_id", _subrole),
        ('SELECT "code", "kind_id" FROM "ability_kinds"', [("weapon", 1), ("ability", 2)])])
    lines = []
    summary = heroes.run(connection, _pull(lines))
    assert asked == [["All heroes", "Doctrine", "Wraith"]]     # the roster's own skipped
    assert written == []
    assert connection.commits == 1 and len(connection.cursors) == 1
    assert summary["cargo_rows"] == 5 and summary["supplemented"] == 3
    assert summary["announced"] == ["Doctrine"]
    assert summary["unknown_heroes"] == ["All heroes", "Wraith"]
    assert summary["missing"] == ["Kite: gone", "Wraith: failed after 1 attempt: gone"]
    assert (summary["weapons"], summary["added"], summary["health"]) == (1, 1, 1)
    assert "heroes" in summary["tables"] and "abilities" in summary["tables"]
    assert lines[:2] == ["cargo rows: 5   heroes named: 4",
                         "supplemented stats: 3  (fields Cargo does not expose)"]
    (cursor,) = connection.cursors
    assert cursor.written("INSERT INTO sources")[0][0] == "wiki"
    assert [params[1] for params in cursor.written("INSERT INTO heroes")] == ["Doctrine"]


def test_the_pull_without_the_articles_reads_the_cargo_table_alone(monkeypatch):
    def refused(*args):
        raise AssertionError("supplement is off: no article is read for the kits")
    monkeypatch.setattr(heroes, "cargo_query", lambda pull, table, fields: ROWS)
    monkeypatch.setattr(heroes, "fetch_articles", lambda *args: Articles({}, ["Doctrine: gone"]))
    monkeypatch.setattr(heroes, "supplement_kits", refused)
    connection = RecordingConnection(reads=[
        ('SELECT "name", "hero_id" FROM "heroes"', [("Anvil", 1)])])
    summary = heroes.run(connection, _pull([]), supplement=False)
    assert summary["supplemented"] == 0 and summary["health"] == 0
    assert summary["missing"] == ["Doctrine: gone"] and summary["announced"] == []
    assert summary["unknown_heroes"] == ["All heroes", "Doctrine"]
