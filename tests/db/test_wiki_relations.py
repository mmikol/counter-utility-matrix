"""The two relations read off wiki articles - synergies and seasons. The
parsers on inline wikitext; then each run() over the wiki page cache inside
a transaction that is rolled back, skipped without the cache or the
database."""

import os
from datetime import date

import psycopg
import pytest

from db import CACHE_DIRS
from db.data.names import name_key
from db.data.wiki import WikiError, seasons, synergies

needs_cache = pytest.mark.skipif(
    not os.path.isdir(CACHE_DIRS["wiki"]), reason="the wiki page cache is not on this machine")


# --- synergies: markup -> claims ---------------------------------------------

WIKITABLE = """
==Abilities==
{|
! |Team Synergy
|-
|[[Genji]]
|x
|Not in the synergy section.
|}

==Match-Ups and Team Synergy==
<!-- [[Hanzo]] in a comment -->
===Tank===
{| class="wikitable mw-collapsible mw-collapsed"
|-
! style="width:75px" |Hero
! |Match-Up
! |Team Synergy</small>
|-
|<center>[[File:icon-dva.png|75px|link=D.Va]]<br />[[D.Va]]</center>
|<small>Her Defense Matrix eats your [[Biotic Grenade]].</small>
|<small>(To be added)</small>
|-
|<center>[[File:Icon-Ramattra.png|75x75px]]<br />[[Ramattra]]</center>
|<small>Keep your distance.</small>
|<small>The combined power of {{Al|Nano Boost}} and [[Annihilation]] is incredible.
Synchronize your attacks.</small>
|-
|<center>[[File:icon-sigma.png|75px|link=Sigma]]<br />[[Sigma]]</center>
|<small>(To be added)</small>
|<small>There are no notable synergies between these heroes.</small> |}

===Damage===
{| class="listtable"
|-
! style="width:80px" |'''Hero'''
! style="width:70%" |'''Match-Up'''
! style="width:30%" |'''Team Synergy'''
|-
!<center>[[Image:icon-genji.png|80px|link=Genji]]<br />[[Genji]]</center>
|'''HIGH RISK'''
<small>He deflects your darts.</small>

|'''TBA SYNERGY'''
<small>Nano-Boost and Dragonblade is popular for a reason.<ref>a [[Tracer]] guide</ref></small>

|-
!<center>[[Image:icon-mei.png|80px|link=Mei]]<br />[[Mei]]</center>
|'''LOW RISK'''
<small></small>

|'''TBA SYNERGY'''
<small></small>

|-
!<center>[[Image:icon-echo.png|80px|link=Echo]]<br />[[Echo]]</center>
|
|'''BAD SYNERGY'''
<small>She flies out of your sight.</small>
|-
|<center>[[Mauga]]</center>
|
|<small>(6v6 Exclusive Pairing - Weak Synergy) Frankly, this is not a good pairing.</small>
|-
|<center>[[Orisa]]</center>
|
|<small>(6v6 Exclusive Pairing - Exceptional Synergy) A match made in heaven.</small>
|}

==Story==
[[Widowmaker]] shot her.
"""

TEMPLATE = """
== Match-Ups and Team Synergy ==
=== Support ===
{{MatchupTable/Support
| Ana_rating = STRONG MATCHUP
| Ana_synergy_rating = STRONG SYNERGY
| Ana_matchup = Dive her.
| Ana_synergy = Ana and Anran have strong synergy, though it requires
coordination.<br><br>A {{al|Nano Boost}} helps.

| Baptiste_synergy_rating = SITUATIONAL SYNERGY
| Baptiste_synergy = Baptiste and Anran do not share ideal positioning.

| JetpackCat_synergy_rating = GOOD SYNERGY
| JetpackCat_synergy = {{al|Lifeline}} [[File:x.png|20px]] tows her behind the enemy.

| Lucio_synergy_rating = MIRROR SYNERGY
| Lucio_synergy =

| Mercy_synergy_rating =
| Mercy_synergy =
}}
"""


def test_a_wikitable_row_is_a_claim_when_its_synergy_cell_holds_advice():
    assert synergies.parse_synergies(WIKITABLE) == [
        ("Ramattra", "The combined power of Nano Boost and Annihilation is incredible."
                     " Synchronize your attacks."),
        ("Genji", "Nano-Boost and Dragonblade is popular for a reason."),
        ("Orisa", "A match made in heaven."),
    ]


def test_a_matchup_template_is_read_by_its_synergy_parameters_and_rating():
    assert synergies.parse_synergies(TEMPLATE) == [
        ("ana", "Ana and Anran have strong synergy, though it requires coordination."),
        ("jetpackcat", "Lifeline tows her behind the enemy."),
    ]


def test_an_article_without_the_section_claims_nothing():
    assert synergies.parse_synergies("==Abilities==\n[[Genji]] is fast.") == []


@pytest.mark.parametrize("cell, rating, advice", [
    ("'''STRONG SYNERGY''' Dive together.", "strong", "Dive together."),
    ("'''TBA SYNERGY'''\n<small>Dive together.</small>", None,
     "<small>Dive together.</small>"),
    ("(6v6 Exclusive Pairing - Ok Synergy) Both fold to poke.", "ok", "Both fold to poke."),
    ("<small>Good synergy with his shield.</small>", None,
     "<small>Good synergy with his shield.</small>"),
])
def test_a_rating_is_split_off_the_advice(cell, rating, advice):
    assert synergies.split_rating(cell) == (rating, advice)


def test_a_note_is_the_first_sentence_cut_to_a_clause_under_the_limit():
    clause = synergies.clause
    assert clause("Nano D.Va. She dives. Then more.") == "Nano D.Va"
    assert clause("You'll end up boosting B.O.B. as his damage wipes teams. More.") == (
        "You'll end up boosting B.O.B. as his damage wipes teams")
    long = ("Enemies snagged by a friendly Roadhog's Chain Hook will usually be reduced to"
            " very low health, which makes them the easiest of targets for a Swift Strike"
            " reset.")
    assert clause(long) == ("Enemies snagged by a friendly Roadhog's Chain Hook will"
                            " usually be reduced to very low health")
    unbroken = "word " * 40
    assert len(clause(unbroken)) < synergies.NOTE_LIMIT and clause(unbroken).endswith("word")


def test_pairs_are_stored_once_and_scored_by_how_many_articles_claim_them():
    ids = {"ana": 1, "genji": 2, "dva": 3, "cassidy": 4}
    pairs, unmatched = synergies.pair_up({
        "Ana": [("Genji", "Nano-Blade."), ("Ana", "Two of you."), ("Sym", "Teleport.")],
        "Genji": [("ana", "Ask for Nano Boost before you draw the blade.")],
        "D.Va": [("McCree", "Matrix his Deadeye.")],
        "Cassidy": [],
    }, ids)
    assert pairs == {(1, 2): (2, "Nano-Blade"), (3, 4): (1, "Matrix his Deadeye")}
    assert unmatched == ["Ana: Sym"]


# --- seasons: markup -> rows -------------------------------------------------

@pytest.mark.parametrize("text, started", [
    ("(4 October 2022 - 6 December 2022)", date(2022, 10, 4)),
    ("[[File:Season 2.png|300px|thumb|Season 2 Roadmap]](6 December 2022 - 7 February 2023)",
     date(2022, 12, 6)),
    ("(16 April 2024 - June 20 2024)", date(2024, 4, 16)),
    ("(June 20, 2024 - August 20, 2024)", date(2024, 6, 20)),
    ("(February 18 - 22 April 2025)", date(2025, 2, 18)),
    ("(October 14 - December 9, 2025)", date(2025, 10, 14)),
    ("(December 9 - February 10, 2026)", date(2025, 12, 9)),
    ("(14 April 2026  - 16 June 2026)", date(2026, 4, 14)),
    ("(October 2026 - December 2026)", None),
    ("It ran long (see Season 3).", None),
])
def test_a_season_starts_on_the_first_date_of_its_run(text, started):
    assert seasons.parse_run(text) == started


def test_the_season_article_names_its_era_subpages():
    text = "===Overwatch 2===\n{{main|Season/2022-2026}}\n{{Main|Season/2026}}\n{{main|Talon}}"
    assert seasons.parse_subpages(text) == ["Season/2022-2026", "Season/2026"]
    with pytest.raises(WikiError):
        seasons.parse_subpages("{{main|Talon}}")


def test_seasons_are_the_numbered_headings_with_their_runs():
    text = ("==List of Seasons==\n===Season 1===\n[[File:Season 1.png|thumb]]\n"
            "(4 October 2022 - 6 December 2022)\n===Minor notes===\n(1 May 2020 - 2 May 2020)\n"
            '===Season 6: Invasion <span class="anchor" id="Season 6"></span>===\n'
            "(10 August 2023 - 10 October 2023)\n==References==\n")
    assert seasons.parse_seasons(text) == [
        ("Season 1", date(2022, 10, 4)), ("Season 6: Invasion", date(2023, 8, 10))]


def test_a_story_arc_subpage_prefixes_its_seasons_with_the_arc():
    text = ("{{SeasonTabs}}\n'''''Reign of Talon''''' is the 2026 arc of ''Overwatch''.\n"
            "===Season 1: Conquest===\n(10 February 2026 - 14 April 2026)\n"
            "=== Season 5: TBA ===\n(October 2026 - December 2026)\n")
    assert seasons.parse_seasons(text) == [
        ("Reign of Talon Season 1: Conquest", date(2026, 2, 10)),
        ("Reign of Talon Season 5: TBA", None)]


# --- the page cache -> the tables ----------------------------------------------

@pytest.fixture()
def sandbox(db, dsn):
    """A connection run() may commit on: nothing lands."""
    connection = psycopg.connect(dsn)
    connection.commit = lambda: None
    yield connection
    connection.rollback()
    connection.close()


@needs_cache
@pytest.mark.invariant
def test_synergies_pull_from_the_cache(sandbox):
    data = synergies.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    rows = sandbox.execute(
        "select s.hero_id, s.other_id, s.score, s.note, src.code"
        " from synergies s join sources src using (source_id)").fetchall()
    assert data["tables"] == ["synergies"] and data["synergies"] == len(rows) > 100
    assert data["mutual"] == sum(1 for row in rows if row[2] == 2) > 0
    assert data["unmatched"] == []

    pairs = [frozenset(row[:2]) for row in rows]
    assert len(set(pairs)) == len(pairs) and all(len(pair) == 2 for pair in pairs)
    assert {row[2] for row in rows} == {1, 2}
    assert {row[4] for row in rows} == {"wiki"}
    for _hero, _other, _score, note, _source in rows:
        assert 10 <= len(note) < synergies.NOTE_LIMIT, note
        assert not any(mark in note for mark in ("[[", "{{", "<", "'''", "\n")), note

    released = dict(sandbox.execute(
        "select hero_id, name from heroes where status = 'released'").fetchall())
    paired = {hero_id for pair in pairs for hero_id in pair}
    assert paired <= set(released)
    unpaired = {line.split(": ", 1)[0]: line.split(": ", 1)[1] for line in data["unpaired"]}
    assert set(unpaired) == {name for hero_id, name in released.items()
                             if hero_id not in paired}
    assert all(unpaired.values())


@needs_cache
@pytest.mark.invariant
def test_the_wiki_states_the_well_known_pairs(sandbox):
    synergies.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    stated = {frozenset((name_key(a), name_key(b))): score for a, b, score in sandbox.execute(
        "select h.name, o.name, s.score from synergies s"
        " join heroes h on h.hero_id = s.hero_id join heroes o on o.hero_id = s.other_id")}
    assert stated[frozenset(("ana", "genji"))] == 2            # both articles say Nano-Blade
    assert frozenset(("pharah", "mercy")) in stated
    assert frozenset(("zarya", "hanzo")) in stated
    assert frozenset(("brigitte", "hanzo")) not in stated      # "no notable team synergy"
    assert frozenset(("anran", "baptiste")) not in stated       # rated SITUATIONAL


@needs_cache
@pytest.mark.invariant
def test_seasons_pull_from_the_cache_and_restamp_the_snapshots(sandbox):
    data = seasons.run(sandbox, cache_dir=CACHE_DIRS["wiki"], log=lambda *_: None)
    rows = sandbox.execute(
        "select s.name, s.started, s.note, src.code from seasons s"
        " join sources src using (source_id) order by s.season_id").fetchall()
    assert data["tables"] == ["seasons", "meta_snapshots"]
    assert data["seasons"] == len(rows) >= 24
    starts = [row[1] for row in rows]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert starts[-1] <= date.today() and data["latest_started"] == starts[-1].isoformat()
    assert {row[3] for row in rows} == {"wiki"}
    assert all(row[2].startswith("Season/") for row in rows)

    by_name = {row[0]: row[1] for row in rows}
    assert by_name["Season 1"] == date(2022, 10, 4)
    assert by_name["Season 9: Champions"] == date(2024, 2, 13)
    assert by_name["Season 15: Honor and Glory"] == date(2025, 2, 18)
    assert by_name["Season 20: Vendetta"] == date(2025, 12, 9)
    assert by_name["Reign of Talon Season 1: Conquest"] == date(2026, 2, 10)
    assert not set(data["upcoming"]) & set(by_name)

    unstamped = sandbox.execute(
        "select count(*) from meta_snapshots where season_id is null"
        " and captured_at::date >= %s", (starts[0],)).fetchone()[0]
    assert unstamped == 0 and data["stamped"] == sandbox.execute(
        "select count(*) from meta_snapshots").fetchone()[0]
