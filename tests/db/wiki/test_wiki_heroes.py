"""The kits pull's readers: a Cargo row's ability type against the shared
vocabulary, an announced hero's article, and what a hero's article adds to
its kit. No database, no network."""

import datetime
import os
import re

import requests

import db
from db.data import fetch
from db.data.wiki.kits.hero_articles import (
    Announcement,
    parse_announcement,
    supplement_from_wikitext,
    supplement_kits,
)
from db.data.wiki.kits.kit_rows import AbilityEntry, HeroKit, ability_kind
from db.data.wiki.kits.measurements import parse_measurements

# --- the ability vocabulary ----------------------------------------------------------

def test_the_ability_vocabulary_is_one_list():
    """The codes db.ABILITY_KINDS names are the rows 002_heroes.sql seeds, in
    the same order, so the writer, the reader and the table cannot drift."""
    path = os.path.join(db.ROOT, "db", "psql", "migrations", "002_heroes.sql")
    with open(path, encoding="utf-8") as handle:
        sql = handle.read()
    block = sql[sql.index("INSERT INTO ability_kinds"):sql.index("AS v(kind_id, code)")]
    seeded = re.findall(r"\(\s*\d+\s*,\s*'([a-z]+)'\s*\)", block)
    assert tuple(seeded) == db.ABILITY_KINDS
    # and the wiki's ability_type maps onto that vocabulary and nothing else
    for base_type, code in (("Weapon;;Hip Fire", db.KIND_WEAPON),
                            ("Ultimate Ability", db.KIND_ULTIMATE),
                            ("Passive", db.KIND_PASSIVE),
                            ("Ability", db.KIND_ABILITY),
                            ("", db.KIND_ABILITY)):
        assert ability_kind(base_type) == code
    assert all(
        ability_kind(t) in db.ABILITY_KINDS
        for t in ("weapon", "WEAPON x", "an ultimate", "a passive", "anything"))


# --- an announced hero, from its article ----------------------------------------------

UPCOMING = """{{Upcoming}}
{{Infobox character
| name = Doctrine
| role = Support
| sub-role = Survivor
| health = 250
}}
'''Doctrine''' is a [[Sub-Roles#Survivor|Survivor]] [[Roles#Support|Support]] hero. He is set to
release in [[Season/2026|Season 5]] on October 6, 2026, which will make him the 54th hero.
"""


def test_an_upcoming_article_yields_the_announcement_and_a_released_one_does_not():
    found = parse_announcement(UPCOMING)
    assert found == Announcement("support", "survivor", 250, datetime.date(2026, 10, 6))
    assert parse_announcement(UPCOMING.replace("{{Upcoming}}", "")) is None     # released
    assert parse_announcement(UPCOMING.replace("| role = Support", "")) is None  # no role, no row
    undated = parse_announcement(UPCOMING.replace("on October 6, 2026", "soon"))
    assert undated and undated.release_date is None


# --- the article supplement ------------------------------------------------------------

KIT_ARTICLE = """{{Ability details
| ability_name = Healing Kasa
| heal = {{tt|90|3.6 every 0.04 seconds}} (1st bounce)<br>{{tt|30|1.2 every 0.04 seconds}} (self)%s
| aoe = 3 meters
}}
{{Ability details
| ability_name = Healing Kasa (old)
| heal = 45
| aoe = 9 meters
}}
""" % (
    '<ref name = "video">2026-02-16,[https://example.org/watch?v=1 How to play].'
    " ''YouTube''</ref>")


def test_an_unfetchable_hero_page_is_reported_rather_than_read_as_empty(tmp_path, instant_wiki):
    """Every per-entity wiki fetch keeps one contract: the failure is recorded
    by name, so a pull that read nothing cannot look like a pull that found
    nothing. The hero whose article fetches is still read."""
    class Down:
        def get(self, *a, **kw):
            raise requests.ConnectionError("the wiki is unreachable")

        def close(self):
            pass

    def kit(name):
        return HeroKit([], [AbilityEntry(name=name, mode=None, input_key=None, keywords="",
                                         description="", stats={}, kind=db.KIND_ABILITY,
                                         display_name=name)], [])

    (tmp_path / "Mizuki.wikitext").write_text(KIT_ARTICLE, encoding="utf-8")
    by_hero = {"Mizuki": kit("Healing Kasa"), "Freja": kit("Quick Dash")}
    added = supplement_kits(
        fetch.PullContext(str(tmp_path), session=Down(), log=lambda line: None), by_hero)
    [line] = added.missing
    assert line.startswith("Freja: ") and "the wiki is unreachable" in line
    assert by_hero["Freja"].abilities[0]["stats"] == {}
    # Mizuki's article adds the heal Cargo leaves empty, and the area
    assert added.stats == 2 and set(by_hero["Mizuki"].abilities[0]["stats"]) == {"heal", "aoe"}
    assert added.profiles == {}                     # the article has no infobox


def test_supplement_reads_heal_and_skips_a_retired_block():
    extra, profile = supplement_from_wikitext(KIT_ARTICLE)
    assert profile is None
    # "(old)" shares the live block's key and comes last: it overwrote it once
    assert set(extra) == {"healing kasa"}
    stats = {code: value for code, (value, _raw) in extra["healing kasa"].items()}
    assert stats == {"heal": "90 (1st bounce); 30 (self)", "aoe": "3 meters"}
    rows = parse_measurements(stats["heal"], "hp")
    assert [(m[0], m[1], m[4]) for m in rows] == [
        (90.0, "hp", "1st bounce"), (30.0, "hp", "self")]
