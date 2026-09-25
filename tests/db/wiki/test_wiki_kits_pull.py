"""The kits pull, db/data/wiki/heroes.py, over a recording connection and
stubbed fetches: an announced hero the Cargo table names is stored from its
article before its kit, a page that will not fetch or names a subrole the
roster lacks is reported and skipped, and run() reads each article once,
stores every kit in one transaction, each hero matched to the roster by
name_key, and counts what it read. No database, no network."""

import datetime

from db.data import fetch
from db.data.wiki import Articles, heroes
from db.data.wiki.kits import hero_articles
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
        ("doctrine", "Doctrine", 3, 7, datetime.date(2026, 10, 6), 50)]
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
    _cargo("All heroes", "Overview", "Ability"),
    _cargo("Wraith", "Shadow Step", "Ability")]

# A hero on the roster whose article still carries the upcoming marker: its
# pools and three stats Cargo lacks.
ANVIL = """{{Upcoming}}
{{Infobox character
| name = Anvil
| role = Support
| sub-role = Survivor
| health = 400
| shield = 0
| armor = 300
}}
{{Ability details
| ability_name = Rocket Hammer
| aoe = 5 meters
| ignores_barrier = yes
| view_angle = 90
}}
"""


def test_the_pull_reads_each_article_once_and_stores_every_kit_in_one_transaction(monkeypatch):
    """Anvil is on the roster and Doctrine is announced by its article, so
    both kits are stored; the overview page is skipped by name, and Wraith's
    article would not fetch, so Wraith stays unknown and is missing once.
    Every hero's article is asked for once, before the first write: Anvil's
    adds its pools and three stats and, the hero being on the roster,
    announces nothing; Doctrine's announces it and sets its pools."""
    asked, written = [], []

    def articles(pull, titles):
        asked.append(list(titles))
        written.extend(text for cursor in connection.cursors for text, _ in cursor.statements
                       if not text.startswith("SELECT"))
        return Articles({"All heroes": "An overview of every hero.", "Anvil": ANVIL,
                         "Doctrine": ARTICLE % ("Doctrine", "Survivor", "Doctrine")},
                        ["Wraith: failed after 1 attempt: gone"])
    monkeypatch.setattr(heroes, "cargo_query", lambda pull, table, fields: ROWS)
    monkeypatch.setattr(hero_articles, "fetch_articles", articles)
    connection = RecordingConnection(reads=[
        ('SELECT "name", "hero_id" FROM "heroes"', [("Anvil", 1)]),
        ("SELECT s.subrole_id, r.role_id", _subrole),
        ('SELECT "code", "kind_id" FROM "ability_kinds"', [("weapon", 1), ("ability", 2)])])
    lines = []
    summary = heroes.run(connection, _pull(lines))
    assert asked == [["All heroes", "Anvil", "Doctrine", "Wraith"]]
    assert written == []
    assert connection.commits == 1 and len(connection.cursors) == 1
    assert summary["cargo_rows"] == 5 and summary["supplemented"] == 3
    assert summary["announced"] == ["Doctrine"]
    assert summary["unknown_heroes"] == ["All heroes", "Wraith"]
    assert summary["missing"] == ["Wraith: failed after 1 attempt: gone"]
    assert (summary["weapons"], summary["added"], summary["health"]) == (1, 1, 2)
    # an announced hero's perks are the pull's rows too
    assert {"heroes", "abilities", "perks"} <= set(summary["tables"])
    assert lines[:2] == ["cargo rows: 5   heroes named: 4",
                         "supplemented stats: 3  (fields Cargo does not expose)"]
    (cursor,) = connection.cursors
    assert cursor.written("INSERT INTO sources")[0][0] == "wiki"
    assert [params[1] for params in cursor.written("INSERT INTO heroes")] == ["Doctrine"]
    # the pools come from the profiles alone, Doctrine's onto the id its row read back
    assert cursor.written("UPDATE heroes") == [(400, 0, 300, 1), (250, None, None, 2)]


def test_a_hero_the_roster_spells_another_way_is_matched_by_its_name_key(monkeypatch):
    """The Cargo table writes Lucio and Soldier 76 where the roster reads
    Lúcio and Soldier: 76: neither is announced from its article, though
    both carry the upcoming marker, and both kits and Lucio's pools land on
    the roster's rows."""
    rows = [_cargo("Soldier 76", "Helix Rockets", "Ability", damage="120"),
            _cargo("Lucio", "Crossfade", "Ability", heal="16")]
    found = {name: ARTICLE % (name, "Survivor", name) for name in ("Lucio", "Soldier 76")}
    monkeypatch.setattr(heroes, "cargo_query", lambda pull, table, fields: rows)
    monkeypatch.setattr(heroes, "supplement_kits", lambda pull, by_hero: Supplement(
        {"Lucio": HeroProfile(health=225, shield=0, armor=0)}, 0, Articles(found, [])))
    connection = RecordingConnection(reads=[
        ('SELECT "name", "hero_id" FROM "heroes"', [("Soldier: 76", 2), ("Lúcio", 3)]),
        ("SELECT s.subrole_id, r.role_id", _subrole),
        ('SELECT "code", "kind_id" FROM "ability_kinds"', [("weapon", 1), ("ability", 2)])])
    summary = heroes.run(connection, _pull([]))
    assert summary["unknown_heroes"] == [] and summary["announced"] == []
    (cursor,) = connection.cursors
    assert not cursor.written("INSERT INTO heroes")
    assert cursor.written("UPDATE heroes") == [(225, 0, 0, 3)]
    assert [params[0] for params in cursor.written("INSERT INTO abilities")] == [3, 2]
