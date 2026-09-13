"""Unit tests: how loose wiki weapon rows become weapons with firing configs.

The trickiest calls in the repo, each shipped wrong once or nearly so:
hip-fire + ADS are ONE weapon, primary + secondary usually merge, but two
weapons of one class (Mauga's chainguns) share a head noun and must NOT."""

from data.authoritative.transform.wiki.weapons import (
    base_name,
    group_weapons,
    head_noun,
)


def entry(name, mode=None):
    return {"name": name, "mode": mode, "input_key": None,
            "display_name": name, "weapon_type": None, "stats": {}}


def names(grouped):
    return [(w, [c["display_name"] for c in cs]) for w, cs in grouped]


def test_hip_fire_and_ads_are_one_weapon_named_for_the_weapon():
    grouped = group_weapons([entry("Biotic Rifle", "Hip Fire"),
                             entry("Zoom (ADS)", "ADS")])
    # the wiki calls the scoped row anything; the config is renamed after
    # the weapon once grouping has decided what the weapon is
    assert names(grouped) == [("Biotic Rifle",
                               ["Biotic Rifle", "Biotic Rifle (ADS)"])]


def test_alt_fire_merges_into_one_weapon():
    grouped = group_weapons([entry("Rivet Gun", "Primary Fire"),
                             entry("Rivet Gun Alternate Fire", "Secondary Fire")])
    assert [w for w, _ in grouped] == ["Rivet Gun"]
    assert len(grouped[0][1]) == 2


def test_primary_and_secondary_with_unrelated_names_merge():
    # one weapon fired two ways, differently named modes
    grouped = group_weapons([entry("Shuriken", "Primary Fire"),
                             entry("Fan of Blades", "Secondary Fire")])
    assert [w for w, _ in grouped] == ["Shuriken"]


def test_two_weapons_of_one_class_stay_separate():
    # Mauga carries two chainguns: shared head noun means siblings, not modes
    grouped = group_weapons([entry("Incendiary Chaingun", "Primary Fire"),
                             entry("Volatile Chaingun", "Secondary Fire")])
    assert [w for w, _ in grouped] == ["Incendiary Chaingun", "Volatile Chaingun"]


def test_form_based_loadouts_stay_separate():
    # no mergeable mode sequence between them - separate weapons
    grouped = group_weapons([entry("Configuration: Recon"),
                             entry("Configuration: Assault")])
    assert len(grouped) == 2


def test_base_name_strips_alt_fire_and_ads_suffixes():
    assert base_name("Rivet Gun Alternate Fire") == "Rivet Gun"
    assert base_name("Take Aim (ADS)") == "Take Aim"


def test_head_noun_is_the_last_word_of_the_base_name():
    assert head_noun("Incendiary Chaingun") == "chaingun"
    assert head_noun("Volatile Chaingun") == "chaingun"
    assert head_noun("The Viper") == "viper"
