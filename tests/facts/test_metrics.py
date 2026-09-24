"""The metrics of facts/compute.py and the sides of facts/draft.py on
the synthetic World: the namespace a strategy reads, the matchup, the map
metrics and the other side's likely six, every expected value worked by
hand from tests/synthetic.py. The team metrics are tests/facts/test_team.py's.
No database."""

import inspect
from collections import Counter

import pytest

from facts import compute
from facts.compute import STAGE_FEATURES, STAGE_MENTIONS, TERRAIN_STANDOUT
from facts.draft import EXPECTED_SHAPE, TEAM_SIZE, is_sided, opposite
from facts.model import TERRAIN_FEATURES
from facts.records import MapRate, StageTerrain
from facts.team import TEAM_METRICS, team_metrics


def test_metrics_cover_the_registry_exactly(synthetic_world):
    w = synthetic_world
    m = w.map("Harbor Gate")
    blue = [w.hero("Balm"), w.hero("Anvil")]
    red = [w.hero("Mortar"), w.hero("Gale")]
    ns = compute.namespace(w, m, red, blue, ban_count=0)
    team_keys = {k for k in ns["team"] if not k.startswith("_")}
    assert team_keys == set(TEAM_METRICS)
    assert set(ns["matchup"]) == set(compute.MATCHUP_METRICS)
    assert set(ns["map"]) == set(compute.MAP_METRICS)
    assert ns["team"]["tanks"] == 1 and ns["team"]["supports"] == 1
    assert ns["enemy"]["flyers"] == 1                     # Gale
    # a flying tank is a flier, not one hitscan is picked to answer
    kite, gale = w.hero("Kite"), w.hero("Gale")
    fliers = team_metrics(w, [kite, gale])
    assert fliers["flyers"] == 2 and fliers["light_flyers"] == 1
    assert compute.registry()["enemy.light_flyers"] == TEAM_METRICS["light_flyers"]
    assert ns["team"]["coverage"] == 1                    # Anvil answers Mortar
    # the benches are the builder's inputs; the roster counts the announced hero
    assert ns["world"] == {"heal_bench": 145.0, "hps_bench": 130.0, "roster_size": 13}
    for key in compute.TEXT_METRICS:
        prefix, name = key.split(".")
        assert name in ns[prefix if prefix != "enemy" else "team"]
    # the solver builds its bag lean: every key a strategy can name reads the same there
    full = team_metrics(w, blue, m, red)
    lean = team_metrics(w, blue, m, red, lean=True)
    for key in compute.registry():
        if key.startswith("team."):
            name = key.split(".", 1)[1]
            assert lean[name] == full[name], key
    assert full["_answered"] == {"Mortar": ["Anvil"], "Gale": []} and lean["_answered"] == {}


def test_metrics_without_a_map_fall_back_honestly(synthetic_world):
    w = synthetic_world
    ns = compute.namespace(w, None, [], [w.hero("Balm")], ban_count=0)
    assert ns["map"]["known"] == 0 and ns["team"]["map_known"] == 0
    assert ns["team"]["map_win_mean"] == ns["team"]["win_mean"] == 50.0      # Balm's own
    assert ns["team"]["map_pick_mass"] == 9.5
    assert ns["team"]["coverage_share"] == 0.0
    assert ns["matchup"]["chew_time_ours"] == ns["matchup"]["chew_time_theirs"] == 999.0


def test_the_matchup_reads_both_sides(synthetic_world):
    """Blue Anvil and Balm: 925 pool, 135 damage a second, a 300 swing, a 70
    heal. Red Mortar and Gale: 762.5 pool with the form's armor, 220 a second,
    a 260 swing, no heal."""
    w = synthetic_world
    blue, red = [w.hero("Anvil"), w.hero("Balm")], [w.hero("Mortar"), w.hero("Gale")]
    blue_t, red_t = team_metrics(w, blue, None, red), team_metrics(w, red, None, blue)
    matchup = compute.matchup_metrics(blue_t, red_t)
    assert matchup == {
        "pool_diff": 162.5, "dps_diff": -85.0, "hps_diff": 60.0,
        "burst_vs_heal": 300.0, "heal_vs_burst": -190.0,
        "chew_time_ours": pytest.approx(762.5 / 135), "chew_time_theirs": pytest.approx(925 / 220),
        "tempo_diff": -1.0, "range_diff": -25.0, "exposure_share": 0.5, "ult_answers": 2}


def test_no_matchup_metric_restates_a_team_metric(synthetic_world):
    """A matchup key must read both sides. One that copies blue's own number
    gives a second name to one signal: two strategies reading it through the
    two names weigh that signal twice, and nothing in the catalog shows it."""
    w = synthetic_world
    blue = [w.hero(n) for n in ("Anvil", "Kite", "Flint", "Needle", "Balm", "Myrrh")]
    red = [w.hero(n) for n in ("Mortar", "Quarry", "Gale", "Rook", "Sorrel", "Tansy")]
    m = w.map("Harbor Gate")
    blue_t = team_metrics(w, blue, m, red)
    red_t = team_metrics(w, red, m, blue)
    matchup = compute.matchup_metrics(blue_t, red_t)

    # a matchup key that equals blue's own is only proof of a copy if it also
    # moves when blue does and red does not: compare a second blue on one red
    other = [w.hero(n) for n in ("Anvil", "Mortar", "Needle", "Rook", "Balm", "Sorrel")]
    other_t = team_metrics(w, other, m, red)
    other_matchup = compute.matchup_metrics(other_t, red_t)

    copies = [
        key for key, value in matchup.items()
        if key in blue_t and value == blue_t[key]
        and other_matchup.get(key) == other_t.get(key)]
    assert not copies, "matchup restates team: %s - read team.* instead" % ", ".join(sorted(copies))


def test_a_map_without_text_reads_zero_for_every_terrain_metric(synthetic_world):
    w = synthetic_world
    bare = compute.map_metrics(w.map("Salt Flats"), ban_count=0)
    assert all(bare[f] == 0.0 for f in TERRAIN_FEATURES)
    none = compute.map_metrics(None, ban_count=0)
    assert all(none[f] == 0.0 for f in TERRAIN_FEATURES)
    read = compute.map_metrics(w.map("Harbor Gate"), ban_count=0)
    assert (read["chokes"], read["hazards"]) == (1.0, -1.0)


def test_the_map_metrics_carry_the_style_on_top_and_its_margin(synthetic_world):
    """Harbor Gate: brawl +2.225 over poke's -0.707."""
    w = synthetic_world
    x = compute.map_metrics(w.map("Harbor Gate"), ban_count=2)
    assert (x["known"], x["mode"], x["bans"]) == (1, "Hybrid", 2)
    assert x["style_top"] == "brawl" and x["style_margin"] == 2.932
    none = compute.map_metrics(None, ban_count=1)
    assert (none["known"], none["style_top"], none["style_margin"], none["bans"]) == (0, "", 0, 1)


def test_map_stages_counts_arenas_and_map_phases_counts_parts_of_a_route(synthetic_world):
    """`map.stages >= 3` guards rules about separate arenas (Control, Flashpoint):
    a Hybrid map's two phases count as map.phases and leave map.stages at 0."""
    w = synthetic_world
    readings = {}
    for name in ("Harbor Gate", "Ember Ruins", "Salt Flats"):
        x = compute.map_metrics(w.map(name), ban_count=0)
        readings[name] = (x["sided"], x["stages"], x["phases"])
    assert readings == {
        "Harbor Gate": (1, 0, 2), "Ember Ruins": (0, 3, 0), "Salt Flats": (0, 0, 0)}
    none = compute.map_metrics(None, ban_count=0)
    assert (none["sided"], none["stages"], none["phases"]) == (0, 0, 0)
    assert compute.arenas(w.map("Ember Ruins")) == ["Courtyard", "Forge", "Spire"]
    assert compute.phases(w.map("Harbor Gate")) == ["Assault", "Escort"]
    assert {"map.stages", "map.phases"} <= set(compute.registry())
    assert not {"map.stages", "map.phases"} & compute.TEXT_METRICS


def test_a_seat_has_a_side_only_on_a_sided_map(synthetic_world):
    w = synthetic_world
    harbor, ember = w.map("Harbor Gate"), w.map("Ember Ruins")
    assert is_sided(harbor) and not is_sided(ember) and not is_sided(None)
    assert compute.map_metrics(harbor, "attack", ban_count=0)["side"] == "attack"
    assert compute.map_metrics(ember, "attack", ban_count=0)["side"] == ""
    assert opposite("attack") == "defense" and opposite("defense") == "attack"
    assert opposite("") == ""


def test_a_stage_stands_out_on_its_own_text_and_enough_mentions(synthetic_world):
    """Stage texts are short: one mention swings a rate, so a feature stands
    out on STAGE_MENTIONS or more. Forge's hazards and Spire's high ground both
    sit one sd up; Forge's text names them twice, Spire's once."""
    w = synthetic_world
    ember = w.map("Ember Ruins")
    assert STAGE_MENTIONS == 2 and TERRAIN_STANDOUT == 0.75
    assert compute.stage_standouts(ember, "Forge") == [("hazards", 1.0)]
    assert ember.stage_z["Spire"]["high_ground"] == 1.0
    assert compute.stage_standouts(ember, "Spire") == []
    assert compute.stage_standouts(ember, "Courtyard") == []        # no text of its own
    # STAGE_FEATURES at most, the largest first, a tie by name
    ember.stage_terrain["Forge"] = {
        f: StageTerrain(9.0, STAGE_MENTIONS) for f in ("cover", "flanks", "hazards")}
    ember.stage_z["Forge"] = {"cover": 0.8, "flanks": 1.5, "hazards": 1.5}
    assert STAGE_FEATURES == 2
    assert compute.stage_standouts(ember, "Forge") == [("flanks", 1.5), ("hazards", 1.5)]


def test_expected_picks_read_the_map_and_the_meta_and_no_strategy(synthetic_world):
    """Red's likely six: their revealed picks first, then the most-picked
    heroes on the map, never a banned hero, never a third tank (the queue's
    own limit), the overall meta when no map is set - each with the rate
    it rests on. No strategy is read: the same six under any playbook."""
    w = synthetic_world
    harbor = w.map("Harbor Gate")
    # announced, and the likeliest pick on record: still never expected
    wisp = w.hero("Wisp")
    wisp.pick, wisp.map_rates = 50.0, {harbor.id: MapRate(50.0, 50.0)}
    kite, needle = w.hero("Kite"), w.hero("Needle")
    six = compute.expected_picks(w, harbor, revealed=[kite], banned=[needle])
    # Anvil's 12 fills the tank seat; Balm's 10 and Gale's 5.5 each gain 2 for a
    # partner already on the six. Flint, Rook and Sorrel then tie at 7: the name
    # gives Flint the last damage seat, though the roster reads Rook first.
    # Unbanned, Needle's 9 would have taken Gale's seat
    assert six == [
        {"hero": "Kite", "role": "tank", "rate": None, "locked": True, "why": "revealed"},
        {"hero": "Anvil", "role": "tank", "rate": 12.0, "locked": False,
            "why": "picked in 12.0% of matches on Harbor Gate"},
        {"hero": "Flint", "role": "damage", "rate": 7.0, "locked": False,
            "why": "picked in 7.0% of matches on Harbor Gate"},
        {"hero": "Gale", "role": "damage", "rate": 5.5, "locked": False,
            "why": "picked in 5.5% of matches on Harbor Gate; pairs with Kite"},
        {"hero": "Balm", "role": "support", "rate": 10.0, "locked": False,
            "why": "picked in 10.0% of matches on Harbor Gate; pairs with Anvil"},
        {"hero": "Sorrel", "role": "support", "rate": 5.0, "locked": False,
            "why": "picked in 5.0% of matches on Harbor Gate; pairs with Gale"}]
    assert len(six) == TEAM_SIZE and Counter(p["role"] for p in six) == EXPECTED_SHAPE
    # deterministic
    assert six == compute.expected_picks(w, harbor, revealed=[kite], banned=[needle])
    anywhere = compute.expected_picks(w, None)
    meta = [("Anvil", 11.0), ("Kite", 9.0), ("Needle", 10.0), ("Rook", 8.0), ("Balm", 9.5),
            ("Tansy", 7.5)]
    assert [(p["hero"], p["rate"]) for p in anywhere] == meta
    assert all(
        p["why"].startswith("picked in %.1f%% of matches overall (no map set)" % rate)
        for p, (_, rate) in zip(anywhere, meta, strict=True))
    # no strategy is read: nothing here takes a catalog
    assert "catalog" not in inspect.signature(compute.expected_picks).parameters


def test_an_expected_pick_says_what_its_rate_rests_on(synthetic_world):
    """A hero with no rate on the map rests on its overall rate and says so; a
    hero with no rate at all rests on none, and a role with nobody left to
    field leaves its seat empty: no other role fills it."""
    w = synthetic_world
    harbor = w.map("Harbor Gate")
    anvil = w.hero("Anvil")
    del anvil.map_rates[harbor.id]
    # Anvil's 11 overall still beats Kite's 8 on the map
    first = compute.expected_picks(w, harbor)[0]
    assert first == {"hero": "Anvil", "role": "tank", "rate": 11.0, "locked": False,
                     "why": "picked in 11.0% of matches overall (no rate on this map)"}
    kite = w.hero("Kite")
    kite.pick, kite.map_rates = None, {}
    banned = [w.hero(n) for n in ("Anvil", "Mortar", "Quarry")]
    five = compute.expected_picks(w, harbor, banned=banned)
    assert len(five) == TEAM_SIZE - 1
    assert [p for p in five if p["role"] == "tank"] == [
        {"hero": "Kite", "role": "tank", "rate": None, "locked": False,
            "why": "no pick rate on record"}]


def test_the_world_metrics_and_the_registry_the_catalog_validates_against(synthetic_world):
    """The world's benches are its own; the registry offers every team metric
    on both sides but the versus keys on red's, which the solver would read as
    zero."""
    assert compute.world_metrics(synthetic_world) == {
        "heal_bench": 145.0, "hps_bench": 130.0, "roster_size": 13}
    reg = compute.registry()
    assert len(reg) == (2 * len(TEAM_METRICS) - len(compute.VERSUS_KEYS)
                        + len(compute.MATCHUP_METRICS) + len(compute.MAP_METRICS)
                        + len(compute.WORLD_METRICS))
    for key in compute.VERSUS_KEYS:
        assert "team." + key in reg and "enemy." + key not in reg, key
    assert reg["team.coverage"] == TEAM_METRICS["coverage"]
    assert all("map.%s" % f in reg for f in TERRAIN_FEATURES)
