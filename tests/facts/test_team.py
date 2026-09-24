"""The team metrics of facts/team.py, section by section, on the synthetic
World: every expected value is worked by hand from tests/synthetic.py, so a
change to the arithmetic fails here whatever the scrape holds. No database."""

import pytest

from facts import compute
from facts.team import FLIER_REACH, SPECIALIST_DELTA, team_metrics


def _picks(w, *names):
    return [w.hero(n) for n in names]


def test_the_shape_counts_roles_and_subroles_and_flags_what_is_off(synthetic_world):
    w = synthetic_world
    t = team_metrics(w, _picks(w, "Anvil", "Kite", "Mortar", "Needle"), w.map("Harbor Gate"))
    assert (t["size"], t["open_slots"], t["tanks"], t["damage"], t["supports"]) == (4, 2, 3, 1, 0)
    assert t["shape_flags"] == ["double tank", "NO SUPPORT"]
    assert t["subroles"] == ["Bruiser", "Initiator", "Sharpshooter", "Stalwart"]
    assert t["subrole_diversity"] == 1.0
    assert t["style_counts"] == {"brawl": 2, "dive": 1, "poke": 1} and t["style_top"] == "brawl"
    assert t["style_lean"] == ""                  # two of four is no strict majority
    assert t["style_fit"] == 0.5                  # Harbor Gate rewards brawl
    assert t["archetype_deviation"] == 1          # one tank over two
    assert team_metrics(w, _picks(w, "Balm"))["shape_flags"] == ["TANKLESS", "solo heal"]


def test_a_style_tie_leans_to_the_style_the_map_rewards(synthetic_world):
    """Flint is dive and poke, Gale dive, Needle poke: two of three each."""
    w = synthetic_world
    trio = _picks(w, "Flint", "Gale", "Needle")
    assert team_metrics(w, trio, w.map("Salt Flats"))["style_lean"] == "poke"
    assert team_metrics(w, trio, w.map("Ember Ruins"))["style_lean"] == "dive"
    assert team_metrics(w, trio)["style_lean"] == "dive"         # no map: by name


def test_a_forms_armor_counts_by_its_uptime_and_a_squishy_pool_at_the_bar(synthetic_world):
    """Mortar spawns with 275 health and 100 armor; its form adds 137.5 armor,
    time-averaged, to the armor and the pool, and not to the spawn pool."""
    w = synthetic_world
    t = team_metrics(w, _picks(w, "Mortar"))
    assert t["armor_total"] == 237.5 and t["pool_total"] == 512.5 and t["weakest"] == "Mortar"
    assert t["armor_share"] == pytest.approx(237.5 / 512.5) and t["pool_min"] == 375
    t = team_metrics(w, _picks(w, "Quarry", "Gale"))
    assert t["shield_total"] == 200 and t["shield_share"] == pytest.approx(200 / 900)
    assert t["squishies"] == ["Gale"] and t["squish_count"] == 1     # 250: at the bar counts
    assert t["weakest"] == "Gale" and t["overhealth_total"] == 0


def test_the_biggest_hit_one_shots_from_range_and_a_melee_swing_does_not(synthetic_world):
    w = synthetic_world
    t = team_metrics(w, _picks(w, "Anvil", "Needle", "Balm"))
    assert t["burst_max"] == 300 and t["burst_hero"] == "Anvil"
    assert t["burst_ranged"] == 250                       # Anvil is melee-only
    assert t["one_shots"] == 1                            # Needle's 250 kills a 250 pool
    alone = team_metrics(w, _picks(w, "Anvil"))
    assert alone["burst_ranged"] == 0 and alone["one_shots"] == 0
    assert team_metrics(w, _picks(w, "Flint"))["one_shots"] == 0
    # Mortar's 260 is a swing: no one-shot, yet a hero with a gun counts toward the ranged hit
    mortar = team_metrics(w, _picks(w, "Mortar"))
    assert mortar["one_shots"] == 0 and mortar["burst_ranged"] == 260


def test_hitscan_answers_a_flier_from_thirty_metres(synthetic_world):
    """Flint publishes 30 m, Rook 25, Needle 70; Gale publishes no reach and
    stays out of the range figures."""
    w = synthetic_world
    assert FLIER_REACH == 30
    t = team_metrics(w, _picks(w, "Flint", "Rook", "Needle", "Gale"))
    assert t["hitscan"] == 3 and t["hitscan_reach"] == 2 and t["projectile"] == 1
    assert (t["range_median"], t["range_max"], t["range_min"]) == (30, 70, 25)
    assert t["dps_floor"] == 500 and t["dps_count"] == 4
    assert t["ult_damage_total"] == 1100 and t["dmg_ults"] == 2      # Rook 500, Gale 600
    assert (t["aoe_count"], t["aoe_damage"], t["beam"], t["melee"]) == (2, 2, 0, 0)
    # Kite's 900 counts at the roster's cap
    assert team_metrics(w, _picks(w, "Kite"))["ult_damage_total"] == 600


def test_the_healing_reads_against_the_rosters_bench(synthetic_world):
    w = synthetic_world
    t = team_metrics(w, _picks(w, "Balm", "Myrrh", "Quarry", "Rook"))
    assert t["hps_floor"] == 140 and t["hps_supports"] == 140
    assert t["hps_ratio"] == pytest.approx(140 / 130)
    assert t["heal_peak_supports"] == 145 and t["heal_ratio"] == 1.0
    assert t["heal_peak_max"] == 75                       # Myrrh's, onto a teammate
    assert t["heal_peak_total"] == 445                    # Quarry's own 300 counts here
    assert t["antiheal"] == 1 and t["heal_amp"] == 0


def test_lifelines_count_any_healing_and_saves_count_what_lands_on_a_teammate(synthetic_world):
    w = synthetic_world
    # Rook heals only off its own damage, Quarry only itself
    assert team_metrics(w, _picks(w, "Rook", "Quarry"))["lifelines"] == 2
    assert team_metrics(w, _picks(w, "Anvil"))["lifelines"] == 0
    # what lands on a teammate, apart from what saves only its owner (Rook's step)
    t = team_metrics(w, _picks(w, "Balm", "Sorrel", "Tansy", "Rook", "Kite"))
    assert t["cleanse"] == 2 and t["team_cleanse"] == 1            # Balm's charm alone
    assert t["invuln"] == 4 and t["team_saves"] == 3               # the charm, the field, the wind
    assert "enemy.team_saves" in compute.registry()


def test_the_tools_count_picks_and_barriers_count_hit_points(synthetic_world):
    w = synthetic_world
    t = team_metrics(w, _picks(w, "Anvil", "Kite", "Mortar", "Myrrh", "Sorrel"))
    assert t["cooldown_count"] == 10 and t["cooldown_median"] == 9.0
    assert t["cc_count"] == 3 and t["mobility_count"] == 3
    assert t["flyers"] == 1 and t["light_flyers"] == 0        # Kite is a tank
    assert t["barrier_hp"] == 1200 and t["barrier_count"] == 1
    assert t["barrier_piercers"] == 1 and t["pierce_dps"] == 100
    assert t["deployables"] == 1


def test_the_synergy_graph_finds_pairs_the_core_and_the_isolated(synthetic_world):
    w = synthetic_world
    t = team_metrics(w, _picks(w, "Anvil", "Balm", "Kite", "Gale", "Sorrel", "Needle"))
    assert t["pairs"] == [("Anvil", "Balm", 2), ("Kite", "Gale", 2), ("Gale", "Sorrel", 1)]
    assert t["synergy_edges"] == 3 and t["synergy_score"] == 5
    assert t["synergy_density"] == pytest.approx(3 / 15)
    assert t["isolated"] == ["Needle"] and t["core_size"] == 3    # Tansy is not here
    # a hero the wiki pairs with no one is unknown, not alone
    assert team_metrics(w, _picks(w, "Flint", "Rook"))["isolated"] == []


def test_the_meta_reads_the_rates_their_spread_and_their_movement(synthetic_world):
    w = synthetic_world
    t = team_metrics(w, _picks(w, "Needle", "Gale", "Rook"))
    assert t["win_mean"] == pytest.approx(51.0) and t["pick_mass"] == 23.0
    assert t["availability"] == pytest.approx(0.70 * 0.88 * 0.95)
    assert t["max_ban_rate"] == 30.0 and t["max_ban_hero"] == "Needle"
    assert t["rank_sensitive_count"] == 1                 # Needle swings 7 points
    assert t["trend_sum"] == 1.0                          # Gale up 2, Rook down 1


def test_the_map_section_reads_each_picks_rates_on_the_map(synthetic_world):
    w = synthetic_world
    assert SPECIALIST_DELTA == 2.5
    t = team_metrics(w, _picks(w, "Anvil", "Rook", "Gale"), w.map("Harbor Gate"))
    assert t["map_known"] == 1 and t["map_pick_mass"] == 24.5
    assert t["map_win_mean"] == pytest.approx((52.5 + 53.5 + 46.5) / 3)
    # Anvil runs exactly SPECIALIST_DELTA over: a specialist; Gale 3 under
    assert t["map_specialists"] == 1 and t["map_offmap"] == 1
    assert t["map_strategy_hits"] == 2                    # Anvil's and Rook's best map
    t = team_metrics(w, _picks(w, "Rook", "Myrrh"), w.map("Ember Ruins"))
    assert (t["map_specialists"], t["map_offmap"], t["map_strategy_hits"]) == (0, 1, 1)
    assert compute.registry()["team.map_strategy_hits"] == (
        "picks whose three best maps by rate include this map")


def test_availability_reads_this_maps_ban_rates_where_it_publishes_them(synthetic_world):
    """Harbor Gate bans Needle 40% and Balm 10%; Anvil's all-ranks 4% stands
    in where the map publishes none."""
    w = synthetic_world
    picks = _picks(w, "Needle", "Balm", "Anvil")
    here = team_metrics(w, picks, w.map("Harbor Gate"))
    assert here["map_availability"] == pytest.approx(0.60 * 0.90 * 0.96)
    assert here["availability"] == pytest.approx(0.70 * 0.92 * 0.96)
    anywhere = team_metrics(w, picks)
    assert anywhere["map_availability"] == anywhere["availability"]


def test_the_versus_section_counts_counter_edges_both_ways(synthetic_world):
    """Anvil answers Mortar and Needle Gale; Gale answers Anvil; no blue pick
    answers Balm."""
    w = synthetic_world
    blue, red = _picks(w, "Anvil", "Needle", "Kite"), _picks(w, "Mortar", "Gale", "Balm")
    t = team_metrics(w, blue, None, red)
    assert t["coverage"] == 2 and t["coverage_share"] == pytest.approx(2 / 3)
    assert t["unanswered"] == ["Balm"] and t["answer_edges"] == 2
    assert t["exposed"] == ["Anvil"] and t["exposure_edges"] == 1 and t["exposed_count"] == 1
    assert t["safe_count"] == 2 and t["net_edges"] == 1 and t["double_covered"] == 0
    assert t["banproof_coverage"] == 1                    # Gale falls with Needle's ban
    assert t["_answered"] == {"Mortar": ["Anvil"], "Gale": ["Needle"], "Balm": []}
    alone = team_metrics(w, blue)
    assert (alone["coverage"], alone["safe_count"], alone["banproof_coverage"]) == (0, 0, 0)


def test_a_metric_read_as_the_wrong_kind_is_the_callers_error():
    """The readers hand a bag's value on as the kind asked for - a number, a
    name, the names, the synergy pairs, the tally, the answers - and a value
    of another kind raises: the catalog keeps text metrics out of every place
    a number is read."""
    from facts import team
    assert team.number(3) == 3 and team.number(2.5) == 2.5
    assert team.numbers({"a": 1, "b": "dive", "c": 2.5, "d": ["x"]}) == {"a": 1, "c": 2.5}
    assert team.text("dive") == "dive"
    assert team.names(["Anvil", "Balm"]) == ["Anvil", "Balm"] and team.names([]) == []
    pair = team.SynergyPair("Anvil", "Balm", 2)
    assert team.synergy_pairs([pair]) == [pair]
    assert team.style_tally({"brawl": 2, "dive": 1}) == {"brawl": 2, "dive": 1}
    assert team.answers({"Mortar": ["Anvil"]}) == {"Mortar": ["Anvil"]}
    for reader, wrong in (
            (team.number, "dive"), (team.number, ["x"]), (team.text, 3),
            (team.names, ["Anvil", 3]), (team.names, "Anvil"),
            (team.synergy_pairs, ["Anvil+Balm"]), (team.synergy_pairs, {}),
            (team.style_tally, {"brawl": "2"}), (team.style_tally, []),
            (team.answers, {"Mortar": "Anvil"}), (team.answers, [])):
        with pytest.raises(TypeError, match="a metric read as"):
            reader(wrong)
