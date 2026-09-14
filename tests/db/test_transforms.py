"""Unit tests: the pure functions the pipelines lean on. No database, no
network - every lesson here was paid for once already."""

from db.data.wiki.maps import parse_stages
from db.data.wiki.measurements import parse_measurements
from db.data.names import name_key


# --- measurements: value / numerator / denominator / window ------------

def test_rate_splits_into_numerator_and_denominator():
    [(value, num, den, window, cond, text)] = parse_measurements("125 m/s")
    assert (value, num, den, window) == (125, "meters", "seconds", 1)


def test_plain_quantity_has_no_denominator():
    [(value, num, den, window, *_)] = parse_measurements("14 seconds")
    assert (value, num, den) == (14, "seconds", None)


def test_window_that_is_not_one_second_is_kept():
    # 75 over 0.59s is a published total, not 127/s; normalising it away
    # would turn a total into a derived rate.
    [(value, num, den, window, *_)] = parse_measurements(
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
    import datetime
    from db.data.wiki.heroes import parse_announcement
    found = parse_announcement(UPCOMING)
    assert found == {"role": "support", "subrole": "survivor", "health": 250,
                     "release_date": datetime.date(2026, 10, 6)}
    assert parse_announcement(UPCOMING.replace("{{Upcoming}}", "")) is None     # released
    assert parse_announcement(UPCOMING.replace("| role = Support", "")) is None  # no role, no row
    undated = parse_announcement(UPCOMING.replace("on October 6, 2026", "soon"))
    assert undated and undated["release_date"] is None
