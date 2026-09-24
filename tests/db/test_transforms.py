"""Unit tests: the pure functions the pulls lean on - the measurement, name
and map readers. No database, no network - every lesson here was paid for
once already."""

import pytest

from db.data.names import name_key
from db.data.wiki import WikiError
from db.data.wiki.kits.measurements import parse_measurements
from db.data.wiki.maps import parse_phases, parse_stages, parse_stretches, stages_of

# --- measurements: value / numerator / denominator / window ------------

def test_rate_splits_into_numerator_and_denominator():
    [(value, num, den, window, _cond, _text)] = parse_measurements("125 m/s")
    assert (value, num, den, window) == (125, "meters", "seconds", 1)


def test_plain_quantity_has_no_denominator():
    [(value, num, den, _window, *_)] = parse_measurements("14 seconds")
    assert (value, num, den) == (14, "seconds", None)


def test_window_that_is_not_one_second_is_kept():
    # 75 over 0.59s is a published total, not 127/s; normalising it away
    # would turn a total into a derived rate.
    [(value, _num, den, window, *_)] = parse_measurements(
        "75 over 0.59 seconds", default_unit="hp")
    assert (value, den, window) == (75, "seconds", 0.59)


def test_range_is_split_and_ordered_by_magnitude():
    # damage falloff is written high -> low; position must not decide min/max
    values = [m[0] for m in parse_measurements("30 - 10 meters")]
    assert values == sorted(values)


def test_perk_transition_keeps_both_sides():
    # "5 -> 7" is the value before the perk AND with it - dropping either
    # side stores the wrong claim (this bug shipped once).
    conds = {m[4] for m in parse_measurements("5 -> 7 meters")}
    assert conds == {"before perk", "with perk"}


def test_booleans_become_one_and_zero():
    assert parse_measurements("✓")[0][0] == 1
    assert parse_measurements("✕")[0][0] == 0


def test_non_numeric_keeps_the_row_with_a_null_value():
    [(value, *_, text)] = parse_measurements("Projectile")
    assert value is None and text == "Projectile"


def test_broken_template_is_not_read_as_a_number():
    [(value, *_)] = parse_measurements("Expression error: unexpected <")
    assert value is None


def test_units_never_contain_a_slash():
    for source in ("125 m/s", "1.25 shots/s", "3 rounds/s"):
        for _, num, den, *_ in parse_measurements(source):
            assert not (num and "/" in num) and not (den and "/" in den)



def test_unicode_minus_reads_as_a_minus():
    # Symmetra's turret slow is written with U+2212; it stored a NULL once.
    [(value, num, den, _window, _cond, text)] = parse_measurements(
        "\u221215% per turret", default_unit="percent")
    assert (value, num, den, text) == (-15.0, "percent", None, "-15% per turret")


def test_bare_per_second_is_a_rate_of_the_stats_own_unit():
    # Death Blossom's "185/s" stored as a flat 185 hp once.
    [(value, num, den, window, *_)] = parse_measurements(
        "185/s per enemy", default_unit="hp")
    assert (value, num, den, window) == (185.0, "hp", "seconds", 1)

# --- name matching across sources ---------------------------------------

def test_name_key_reconciles_source_spellings():
    # a fold that strips the accent to a space turns Lucio into "Lu io" -
    # NFKD + drop combining marks is the one that works
    assert name_key("Lúcio") == name_key("Lucio")
    assert name_key("D.Va") == name_key("DVa")
    assert name_key("Soldier: 76") == name_key("soldier-76")
    assert name_key("King's Row") == name_key("Kings Row")


# --- map stages out of article wikitext ----------------------------------

FIXTURE = """
==Background==
lore
==Gameplay==
Each turn is played on one of the sections:
[[File:x.png|thumb|caption]]
* Downtown
** Downtown is a description sentence. It must not load as a stage.
* Sanctuary
*[[MEKA Base]]
=== Stadium ===
* Stadium Map That Must Not Leak
==Strategy==
* not a stage either
"""


def test_stages_are_top_level_gameplay_bullets_only():
    assert parse_stages(FIXTURE) == ["Downtown", "Sanctuary", "MEKA Base"]


def test_prose_only_maps_have_no_stages():
    assert parse_stages("==Gameplay==\nA payload route in prose.\n") == []


def test_fewer_than_two_bullets_is_not_a_stage_list():
    assert parse_stages("==Gameplay==\n* Lone bullet\n") == []


# --- an Escort map's stretches, a Hybrid map's phases ---------------------------

ESCORT_NAMED = """
==Background==
=== The Old Quarter ===
lore
== Gameplay ==
[[File:Harbour View.webp|thumb|Harbour View]]
Harbour is an [[Escort]] map which takes place in three main locations: The
City Streets, a [[Rum|Distillery]], and the Sea Fort.

=== City Streets ===
A long open street.

===<u>Distillery</u>===
An enclosed building.

=== The Sea Fort ===
A straight with minimal cover.

===Ferry Rides===
Ferries cross the water.

== Strategy ==
=== Heroes ===
"""

ESCORT_UNNAMED = """
==Gameplay==
The payload starts at the docks, passes the market and ends in the [[hangar]].

==Strategy==
=== Attack ===
Take the high ground.
"""

HYBRID_PAGE = """[[File:Hybrid.png|right|frameless]]
'''Hybrid''' is one of the main [[game mode]]s. It is a combination of the
[[Assault]] and [[Escort (game mode)|Escort]] modes.

==Gameplay==
In the first section, the attacking team must capture a point.
"""


def test_stretches_are_the_gameplay_subsections_the_opening_names():
    # a leading article aside; Ferry Rides is a subsection, not a stretch
    assert parse_stretches(ESCORT_NAMED) == ["City Streets", "Distillery", "The Sea Fort"]


def test_an_escort_article_that_names_no_stretch_stores_none():
    assert parse_stretches(ESCORT_UNNAMED) == []
    assert stages_of("escort", ESCORT_UNNAMED, ["Assault", "Escort"]) == []
    # subsections its opening does not list are not stretches
    assert parse_stretches("==Gameplay==\nA route.\n=== Docks ===\n=== Market ===\n") == []
    assert parse_stretches("==Background==\nlore\n") == []


def test_the_hybrid_article_names_the_two_phases_in_play_order():
    # a piped link gives its label
    assert parse_phases(HYBRID_PAGE) == ["Assault", "Escort"]
    assert parse_phases("a combination of [[Assault]] and [[Escort]].") == ["Assault", "Escort"]
    with pytest.raises(WikiError):
        parse_phases("Hybrid is a [[game mode]].")


def test_a_maps_stages_follow_its_mode():
    phases = ["Assault", "Escort"]
    assert stages_of("control", FIXTURE, phases) == ["Downtown", "Sanctuary", "MEKA Base"]
    assert stages_of("flashpoint", FIXTURE, phases) == ["Downtown", "Sanctuary", "MEKA Base"]
    assert stages_of("escort", ESCORT_NAMED, phases) == [
        "City Streets", "Distillery", "The Sea Fort"]
    # every Hybrid map plays the two phases, whatever its article lists
    assert stages_of("hybrid", ESCORT_NAMED, phases) == phases
    assert stages_of("hybrid", "", phases) == phases
    # a Push map stays whole
    assert stages_of("push", FIXTURE, phases) == []
    assert stages_of("push", ESCORT_NAMED, phases) == []
