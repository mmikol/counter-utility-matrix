"""The counters read off the wiki's Match-Up cells: the row parser on inline
wikitext in both markups, the verdict on single cells, two articles
combined. The pull is test_wiki_matchups_pull.py's."""

import pytest

from db.data.wiki import matchup_tables, matchups
from db.data.wiki.matchups import Known, read_cell

# --- markup -> rows ----------------------------------------------------------

WIKITABLE = """
==Match-Ups and Team Synergy==
===Tank===
{| class="wikitable mw-collapsible mw-collapsed"
|-
! style="width:75px" |Hero
! |Match-Up
! |Team Synergy
|-
|<center>[[File:icon-dva.png|75px|link=D.Va]]<br />[[D.Va]]</center>
|<small>D.Va is a significant threat to you. Beating her in a 1v1 is near impossible.</small>
|<small>(To be added)</small>
|-
|<center>[[Orisa]]</center>
|<small>(To be added)</small>
|<small>Her Fortify holds the line for you.</small>
|-
![[File:Icon-Hazard.png|center|thumb|80x80px|[[Hazard]]]]
|<small>Hazard can be an interesting matchup.</small>
|<small>(To be added)</small>
|-
|<center>[[Widowmaker]]</center>
|<small>The enemy Widowmaker should be your first target.</small>
|
|}

===Damage===
{| class="listtable"
|-
! style="width:80px" |'''Hero'''
! style="width:70%" |'''Match-Up'''
! style="width:30%" |'''Team Synergy'''
|-
!<center>[[Image:icon-pharah.png|80px|link=Pharah]]<br />[[Pharah]]</center>
|'''LOW RISK'''
<small>Pharah's slow flight makes her a prime target for you at a distance.</small>

|'''TBA SYNERGY'''
<small></small>
|-
!<center>[[McCree]]</center>
|'''Very Strong Vs.'''
<small>He cannot reach you.</small>
|
|-
!<center>[[Mei]]</center>
|'''TBA RISK'''
<small></small>
|
|}
"""

TEMPLATE = """
== Match-Ups and Team Synergy ==
=== Tank ===
{{MatchupTable/Tank
| dva_rating = VERY WEAK MATCHUP
| dva_risk = EXTREME RISK
| dva_matchup =
| dva_synergy_rating = GOOD SYNERGY
| dva_synergy = She peels for you.

| reinhardt_rating = EVEN -> STRONG MATCHUP
| reinhardt_risk = LOW RISK
| reinhardt_matchup = Reinhardt has no way to reach Pharah. He is an easy target for her rockets.

| soldier76_rating = EXTREMELY HIGH PRIORITY TARGET
| soldier76_risk = EXTREME RISK
| soldier76_matchup = Soldier: 76 is one of Pharah's most notorious counters.

| roadhog_rating = MEDIUM MATCHUP
| roadhog_risk = HIGH RISK
| roadhog_matchup = His hook is a death sentence.

| sigma_rating =
| sigma_risk =
| sigma_matchup =
}}
"""


def test_the_shared_row_parser_reads_the_match_up_column_of_a_wikitable():
    rows = dict(matchup_tables.section_rows(WIKITABLE, matchup_tables.MATCHUP))
    assert list(rows) == ["D.Va", "Orisa", "Hazard", "Widowmaker", "Pharah", "McCree", "Mei"]
    assert rows["Hazard"] == "<small>Hazard can be an interesting matchup.</small>"
    hazard = matchup_tables.section_rows(WIKITABLE, matchup_tables.MATCHUP)[2]
    assert (hazard.hero, hazard.cell) == ("Hazard", rows["Hazard"])
    assert rows["Pharah"].startswith("'''LOW RISK'''\n<small>Pharah's slow flight")
    # The synergy column of the same rows is untouched by the match-up one.
    assert dict(matchup_tables.section_rows(WIKITABLE))["Orisa"] == (
        "<small>Her Fortify holds the line for you.</small>")


def test_the_shared_row_parser_reads_a_template_with_its_ratings_leading_the_cell():
    rows = dict(matchup_tables.section_rows(TEMPLATE, matchup_tables.MATCHUP))
    assert list(rows) == ["dva", "reinhardt", "soldier76", "roadhog", "sigma"]
    assert rows["dva"] == "'''VERY WEAK MATCHUP | EXTREME RISK''' "
    assert rows["soldier76"].startswith("'''EXTREMELY HIGH PRIORITY TARGET | EXTREME RISK''' ")
    assert rows["sigma"] == ""
    assert dict(matchup_tables.section_rows(TEMPLATE))["dva"] == (
        "'''GOOD SYNERGY''' She peels for you.")


def test_a_wikitable_article_gives_a_reading_per_written_cell():
    readings = dict(matchups.parse_matchups(WIKITABLE, "Widowmaker", {}))
    # Unwritten: Orisa "(To be added)", Mei an empty TBA cell. The mirror row is skipped.
    assert list(readings) == ["D.Va", "Hazard", "Pharah", "McCree"]
    assert {name: reading.verdict for name, reading in readings.items()} == {
        "D.Va": -1, "Hazard": 0, "Pharah": 1, "McCree": 1}
    assert readings["McCree"].basis == "rating" and readings["Pharah"].basis == "prose"
    assert readings["D.Va"] == (-1, "prose")


def test_a_template_article_is_read_by_the_roster_name_and_pronoun():
    known = {
        "pharah": Known("Pharah", "she"), "soldier76": Known("Soldier: 76", "he"),
        "reinhardt": Known("Reinhardt", "he"), "roadhog": Known("Roadhog", "he")}
    readings = dict(matchups.parse_matchups(TEMPLATE, "Pharah", known))
    assert list(readings) == ["dva", "reinhardt", "soldier76", "roadhog"]
    assert readings["dva"] == (-1, "rating")
    # "EVEN -> STRONG" is half a step: the prose decides, "her rockets" being Pharah's.
    assert readings["reinhardt"].basis == "prose" and readings["reinhardt"].verdict == 1
    assert readings["soldier76"].verdict == -1
    assert readings["roadhog"] == (0, "rating")


def test_an_article_without_the_section_reads_nothing():
    assert matchups.parse_matchups("==Abilities==\n[[Genji]] is fast.", "Ana", {}) == []


# --- a cell -> a verdict -----------------------------------------------------

@pytest.mark.parametrize("cell, verdict", [
    # a threat
    ("<small>Reaper is one of your worst nightmares. He can tear through your health.</small>", -1),
    ("<small>Reaper is a hard counter to you.</small>", -1),
    ("<small>You will struggle against Reaper, and there is little you can do.</small>", -1),
    # an advantage
    ("<small>You are by far one of the strongest counters to Reaper.</small>", 1),
    ("<small>Reaper is an easy target for you: he cannot escape your Tesla Cannon.</small>", 1),
    ("<small>Being a melee fighter, Reaper poses little threat to you.</small>", 1),
    # a negation reverses a cue
    ("<small>Reaper is not a threat to you at long distances.</small>", 1),
    ("<small>Reaper doesn't pose a huge threat to you.</small>", 1),
    (
        "<small>Reaper's Wraith Form can't negate your Tesla Cannon, and he is not an easy target."
        "</small>", 0),
    # a hedge after the verdict does not undo it; a verdict only hedged is none
    (
        "<small>Reaper is one of your worst nightmares. That said, he is an easy target while he"
        " reloads.</small>", -1),
    (
        "<small>Use cover. Watch his flank routes. Save your cooldowns. Stay with your team. If you"
        " are alone, he can kill you.</small>", 0),
    (
        "<small>While Reaper is a threat up close, you are a strong counter to him at range."
        "</small>", 1),
    # advice with no cue
    ("<small>Destroy his Shadow Step marker when you see it.</small>", 0),
])
def test_prose_is_read_from_the_article_heros_seat(cell, verdict):
    assert read_cell(cell, "Winston", "Reaper").verdict == verdict


@pytest.mark.parametrize("cell, verdict, basis", [
    ("'''STRONG MATCHUP''' He is a threat to you.", 1, "rating"),
    ("'''Very Weak Vs.'''\n<small>You are his counter.</small>", -1, "rating"),
    ("'''MIRROR MATCHUP | MEDIUM RISK''' He is a threat to you.", 0, "rating"),
    ("'''WEAK -> VERY WEAK MATCHUP''' ", -1, "rating"),
    # Half a step leaves the prose to decide.
    ("'''EVEN -> WEAK MATCHUP''' You are one of his strongest counters.", 1, "prose"),
    ("'''EVEN -> WEAK MATCHUP''' Trade cooldowns evenly.", 0, "prose"),
    # RISK is a cue: EXTREME decides alone, HIGH does not. PRIORITY TARGET is not a verdict.
    ("'''<nowiki>HIGH PRIORITY | EXTREMELY HIGH RISK</nowiki>'''", -1, "prose"),
    ("'''HIGH RISK'''\n<small></small>", 0, "prose"),
    ("'''HIGH RISK'''\n<small>He can easily kill you.</small>", -1, "prose"),
    ("'''EXTREMELY HIGH PRIORITY TARGET''' Kill him first.", 0, "prose"),
    ("'''VERY LOW RISK''' ", 1, "prose"),
])
def test_the_wikis_rating_is_read_before_the_prose(cell, verdict, basis):
    reading = read_cell(cell, "Winston", "Reaper")
    assert (reading.verdict, reading.basis) == (verdict, basis)


@pytest.mark.parametrize("cell", [
    "<small>(To be added)</small>", "(to be added)", "", "'''TBA RISK'''\n<small></small>",
    "'''TBA PRIORITY TARGET''' <small>TBA</small>",
])
def test_a_placeholder_cell_is_unwritten(cell):
    assert read_cell(cell, "Winston", "Reaper") == matchups.UNWRITTEN


def test_names_and_pronouns_are_put_in_the_heros_seat():
    normalise = matchups.normalise
    assert normalise("Soldier: 76's Helix Rockets hurt you; he outranges Pharah.",
                     "Pharah", "Soldier: 76") == "foe's Helix Rockets hurt you; foe outranges you."
    # Third person: a pronoun is the hero's or the enemy's by what their articles use.
    text = "Wrecking Ball is probably one of her biggest counters. She can't hit him."
    assert normalise(text, "Wrecking Ball", "Widowmaker", ("he", "she")) == (
        "you is probably one of foe's biggest counters. foe can't hit you.")
    # Same pronoun, no "you": the last of the two named.
    assert normalise("Ana outranges Mercy. Her pistol is weak.", "Ana", "Mercy",
                     ("she", "she")) == "you outranges foe. foe's pistol is weak."
    assert normalise("Keep him away; he's an easy target.", "Ana", "Reaper") == (
        "Keep foe away; foe is an easy target.")


def test_a_heros_former_name_and_its_name_unpunctuated_read_as_the_hero():
    normalise = matchups.normalise
    assert normalise("McCree's Flashbang stops you.", "Winston", "Cassidy") == (
        "foe's Flashbang stops you.")
    assert normalise("Soldier 76 outranges Pharah.", "Pharah", "Soldier: 76") == (
        "foe outranges you.")


def test_a_heros_pronoun_is_counted_outside_the_match_up_section():
    article = (
        "He is a scientist. His cannon arcs. He leaps.\n"
        "==Match-Ups and Team Synergy==\nShe snipes. Her mine. She hooks. Her. She.\n"
        "==Story==\nHe left the moon.")
    assert matchups.pronoun(article) == "he"
    assert matchups.pronoun("They dig.") is None


def test_two_articles_agree_into_one_edge_and_contradict_into_none():
    def reading(verdict):
        return matchups.Reading(verdict, "prose")

    ids = {"winston": 1, "widowmaker": 2, "reaper": 3, "cassidy": 4, "ana": 5}
    edges, contradicted, unmatched = matchups.combine({
        "Winston": [("Widowmaker", reading(1)), ("Reaper", reading(-1)),
                    ("McCree", reading(1)), ("Ana", reading(0)),
                    ("Winston", reading(1)), ("Sym", reading(1))],
        "Widowmaker": [("Winston", reading(-1))],
        "Reaper": [("Winston", reading(0))],
        "Cassidy": [("Winston", reading(1))],
        "Ana": [],
    }, ids)
    # (loser, winner): both articles agree on Widowmaker; Reaper's says neither;
    # Cassidy's and Winston's each claim the pair.
    assert edges == {(2, 1), (1, 3)}
    assert contradicted == [(1, 4)]
    assert unmatched == ["Winston: Sym"]
