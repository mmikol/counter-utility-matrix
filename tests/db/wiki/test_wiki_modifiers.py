"""Unit tests: what a buff or debuff scales and who it lands on, read off
the wiki's wording - the value's qualifier and the ability's keywords. The
table is (stat_code, value_text, keywords) -> the answer; a row that fails
is a regression in the readers, not in the table. No database."""

import pytest

from db.data.wiki.modifiers import MODIFIER_STATS, affected_quantity, applies_to


@pytest.mark.parametrize("stat, value, keywords, affects", [
    ("heal", "50", "", None),                               # a value, not a modifier
    ("mspeed_slow", "-30%", None, "movement_speed"),
    ("mspeed_buff", None, None, "movement_speed"),
    ("healing_mod", "+50% received", "", "healing_received"),
    ("healing_mod", "+25% Dealt", "", "healing_dealt"),
    ("healing_mod", "+25%", "amp outgoing", None),          # healing reads only the value
    ("damage_red", "50%", "", "damage_taken"),
    ("damage_red", "50% dealt", "", "damage_taken"),        # a reduction is always taken
    ("damage_amp", "+25% taken", "", "damage_taken"),
    ("damage_amp", "+30%", "Amp Incoming", "damage_taken"),
    ("damage_amp", "+50% dealt", "", "damage_dealt"),
    ("damage_amp", "+50%", "amp outgoing", "damage_dealt"),
    ("damage_amp", "+50%", None, None),                     # the source does not say
    ("damage_amp", "+10% dealt", "amp incoming", "damage_taken"),   # taken comes first
])
def test_what_a_modifier_scales_is_read_off_its_wording(stat, value, keywords, affects):
    assert affected_quantity(stat, value, keywords) == affects


@pytest.mark.parametrize("stat, value, keywords, target", [
    ("healing_mod", "+50%", "target ally", "ally"),
    ("damage_amp", "+30%", "Target Ally, Amp Incoming", "ally"),    # a named ally comes first
    ("damage_amp", "+30%", "amp incoming", "enemy"),
    ("damage_amp", "+25% taken", "", "enemy"),
    ("damage_red", "50%", "", "self"),
    ("damage_red", "50%", "target enemy", None),
    ("damage_red", "50%", "Target Ally", "ally"),
    ("damage_amp", "+50% dealt", "", None),
    ("mspeed_buff", None, None, None),
])
def test_who_a_modifier_lands_on_is_read_off_its_keywords(stat, value, keywords, target):
    assert applies_to(stat, value, keywords) == target


def test_the_modifier_families_are_the_three_the_rules_read():
    # affected_quantity sends any other family through the damage rules, so a
    # new family needs its own branch before it joins the table
    assert set(MODIFIER_STATS.values()) == {"damage", "healing", "movement_speed"}
