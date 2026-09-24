"""A team's facts and the matchup's from facts/team_facts.py, written
straight from a board on the synthetic World: one fact per team metric,
worded around the number the solver scores, each side's versus facts once
the other side has picks, and the matchup once both do. Every sentence is
worked from tests/synthetic.py. No database."""

from facts import team_facts
from facts.draft import Draft
from facts.factset import FactSet
from facts.model import Resolved
from facts.team import team_metrics


def _facts(world, map_name, red, blue):
    board = Resolved(world.map(map_name) if map_name else None,
                     [world.hero(n) for n in red], [world.hero(n) for n in blue], [])
    fs = FactSet(Draft(map_name, tuple(red), tuple(blue)))
    team_facts.write(fs, world, board)
    return fs


def _said(fs, team=None):
    """{key: sentence} for one side's team facts, or the matchup's."""
    if team is None:
        return {f.key: f.text for f in fs.facts if f.scope == "matchup"}
    return {f.key: f.text for f in fs.facts if f.team == team and f.key != "team.answer"}


def test_a_side_is_worded_metric_by_metric(synthetic_world):
    """Anvil, Kite, Mortar and Needle on Harbor Gate, red empty: 2062.5 pool,
    837.5 of it armor with Mortar's form, 385 damage a second, no healing."""
    fs = _facts(synthetic_world, "Harbor Gate", (), ("Anvil", "Kite", "Mortar", "Needle"))
    said = _said(fs, "blue")
    assert said["team.size"] == (
        "blue team: 4 picks locked (Anvil, Kite, Mortar, Needle), 2 slots open")
    assert said["team.tanks"] == (
        "blue team shape: 3 tank / 1 dps / 0 support - double tank; NO SUPPORT")
    assert said["team.subrole_diversity"] == (
        "blue team subrole diversity: 4 distinct jobs across 4 picks"
        " (Bruiser, Initiator, Sharpshooter, Stalwart)")
    assert said["team.style_top"] == (
        "blue team style profile: brawl 2/4, dive 1/4, poke 1/4 - no majority style")
    assert said["team.style_fit"] == (
        "blue team fit with the brawl style Harbor Gate rewards: 50% of picks")
    assert said["team.archetype_deviation"] == "blue team over two per role: 1 pick"
    assert said["team.pool_total"] == "blue team effective HP: 2062 across 4 picks"
    assert said["team.pool_min"] == (
        "blue team weakest link: Needle at 200 pool - focus fire finds the minimum")
    assert said["team.armor_share"] == (
        "blue team armor: 837 of 2062 pool (41%) discounts sustained fire")
    assert said["team.dps_floor"] == (
        "blue team sustained damage: 385 per second, held weapons summed, 4 of 4 picks with"
        " a figure")
    assert said["team.burst_max"] == "blue team burst ceiling: Anvil's 300 in one hit"
    # listed(): the registry's own line, for a metric no sentence is written for
    assert said["team.burst_ranged"] == (
        "blue team the biggest single hit from a pick that is not melee-only: 260")
    assert said["team.range_median"] == (
        "blue team reach: median 22.5m across the 4 of 4 picks whose weapons publish one"
        " (5m to 70m) - reads as poke")
    assert said["team.cooldown_median"] == (
        "blue team cooldown tempo: median 8s across 8 cooldowns - high-uptime brawl tempo")
    assert said["team.cc_count"] == (
        "blue team crowd control: 2 picks; Anvil: Quake Slam; Mortar: Grasping Pit")
    assert said["team.barrier_hp"] == "blue team barriers: 1200 hp across 1 pick"
    assert said["team.isolated_count"] == (
        "blue team isolated: Anvil, Kite, Mortar, Needle, with no documented partner on the team")
    assert said["team.pick_mass"] == (
        "blue team pick-rate mass: 35.0 summed - meta-shaped; expect practiced answers")
    # Needle's 40% ban on this map is the difference between the two
    assert said["team.map_availability"] == (
        "blue team availability on Harbor Gate: 51% chance every pick survives the ban"
        " screen here, from this map's ban rates")
    assert said["team.availability"] == (
        "blue team expected availability: 59% chance every pick survives the ban screen"
        " (Needle at 30% ban)")
    assert said["team.map_win_mean"] == (
        "blue team on Harbor Gate: mean win rate 50.9% (pick mass 35.0)")
    assert said["team.map_specialists"] == (
        "blue team map fit on Harbor Gate: 1 specialist, 0 off-map, 2 with this map among"
        " their three best by rate")
    # no heal, no shields, no enemy: none of their facts, and no matchup
    assert "team.hps_supports" not in said and "team.shield_share" not in said
    assert "team.coverage" not in said and not _said(fs)


def test_every_team_fact_carries_the_number_the_solver_scores(synthetic_world):
    """A fact's value is its metric's value in team_metrics, and its source
    names the metric: what the board states is what a strategy reads."""
    w = synthetic_world
    red, blue = ("Gale", "Kite", "Rook"), ("Anvil", "Mortar", "Needle", "Flint", "Balm", "Myrrh")
    fs = _facts(w, "Harbor Gate", red, blue)
    m = w.map("Harbor Gate")
    for team, own, other in (("red", red, blue), ("blue", blue, red)):
        metrics = team_metrics(w, [w.hero(n) for n in own], m, [w.hero(n) for n in other])
        facts = [f for f in fs.facts if f.team == team and f.key != "team.answer"]
        assert facts
        for f in facts:
            key = f.key.split(".", 1)[1]
            assert f.value == metrics[key] and f.source == "derived:" + f.key, f.key
    # each enemy's answerers, by name
    assert [f.text for f in fs.find("team.answer", "blue")] == [
        "red Gale is answered by blue Needle, Flint"]
    assert [f.text for f in fs.find("team.answer", "red")] == [
        "blue Anvil is answered by red Gale", "blue Needle is answered by red Kite",
        "blue Balm is answered by red Rook"]


def test_the_healing_and_the_saves_read_against_the_rosters_bench(synthetic_world):
    """Balm alone heals 60 a second and 70 a cast against benches of 130 and
    145; two supports under UNDER_HEALED of the bench are flagged."""
    w = synthetic_world
    said = _said(_facts(w, "Harbor Gate", ("Mortar", "Gale"), ("Anvil", "Balm")), "blue")
    assert said["team.hps_supports"] == (
        "blue team healing supply: 60 per second sustained across the supports vs the"
        " roster's ~130 two-support bench (ratio 0.46)")
    assert said["team.heal_peak_supports"] == (
        "blue team biggest single heals: 70 summed across the supports vs the roster's"
        " ~145 two-support bench (ratio 0.48)")
    assert said["team.lifelines"] == "blue team lifelines: 1 of 2 picks carry any healing"
    assert said["team.invuln"] == "blue team defensive answers: 1 invulnerability, 1 cleanse"
    assert said["team.team_saves"] == (
        "blue team picks with an invulnerability, death-prevention or cleanse that lands on"
        " a teammate: 1")
    assert said["team.synergy_edges"] == (
        "blue team cohesion: 1 of 1 possible synergy edges (density 1.00, score sum 2)"
        " - Anvil+Balm")
    assert said["team.coverage"] == (
        "blue team coverage: answers 1/2 red picks; still unanswered: Gale")
    assert said["team.exposed_count"] == (
        "blue team exposed: Anvil answered by at least one red pick; 1 safe")
    assert said["team.banproof_coverage"] == (
        "blue team ban-resilient coverage: without Balm (8% ban) still 1/2 answered")
    # Balm and Tansy sustain 115 a second: under 0.7 of a 200 bench
    w.hps_bench = 200.0
    thin = _said(_facts(w, None, (), ("Balm", "Tansy")), "blue")
    assert thin["team.hps_supports"] == (
        "blue team healing supply: 115 per second sustained across the supports vs the"
        " roster's ~200 two-support bench (ratio 0.57) - UNDER-HEALED")
    # one pick has no synergy graph, and no map no map facts
    alone = _said(_facts(w, None, (), ("Gale",)), "blue")
    assert "team.synergy_edges" not in alone and "team.map_win_mean" not in alone


def test_the_matchup_is_worded_once_both_sides_have_picks(synthetic_world):
    """Blue Anvil and Balm against red Mortar and Gale: the numbers of
    test_the_matchup_reads_both_sides, in words."""
    w = synthetic_world
    assert not _said(_facts(w, "Harbor Gate", ("Mortar", "Gale"), ()))
    said = _said(_facts(w, "Harbor Gate", ("Mortar", "Gale"), ("Anvil", "Balm")))
    assert said == {
        "matchup.pool_diff": "pool differential: blue's 2 picks carry 925 hp vs red's 2"
            " picks' 762 - +162 raw material",
        "matchup.dps_diff": "damage floor differential: blue 135/s vs red 220/s (-85)",
        "matchup.hps_diff": "healing floor differential: blue 60/s vs red 0/s (+60)",
        "matchup.burst_vs_heal": "burst-vs-heal, blue's way: blue's best hit 300 vs red's"
            " best save 0 - a kill window exists through their healing",
        "matchup.heal_vs_burst": "burst-vs-heal, red's way: red's best hit 260 vs blue's"
            " best save 70 - red's burst outruns blue's save; do not trade in the open",
        "matchup.chew_time_ours": "chew-time floor, blue into red: 762 pool / 135 per second"
            " = 5.6s of unmitigated fire (no healing, no misses)",
        "matchup.chew_time_theirs": "chew-time floor, red into blue: 925 pool / 220 per"
            " second = 4.2s",
        "matchup.tempo_diff": "tempo war: blue median cooldown 8.5s vs red 7.5s - red"
            " re-engages first; make each fight decisive",
        "matchup.range_diff": "poke war: blue median reach 5m vs red 30m - red outranges;"
            " close fast or trade cover",
        "matchup.net_edges": "board net matchup: 1 blue answer-edges into red vs 1 red into"
            " blue (+0) - dead even",
        "matchup.coverage_share": "coverage: blue answers 50% of red; red answers 50% of blue",
        "matchup.dive_pressure": "dive pressure: 1 pick on red carry engage tools; blue peel"
            " (1 crowd-control pick) must hold",
        "matchup.flyers": "vertical threat: 1 flyer on red against 0 hitscan picks on blue",
        "matchup.ult_threat": "ult threat: red's damage ultimates total 600 against 2"
            " invulnerability or cleanse answers on blue",
        "matchup.style_lean_red": "style war: red leans nothing yet, blue leans brawl"}


def test_the_matchup_names_each_side_of_every_trade(synthetic_world):
    """Blue Gale, Rook and Kite answer all three of red's Anvil, Balm and
    Needle and cycle faster; red brings a barrier and a heal. Two mirrored
    supports trade evenly on every count."""
    w = synthetic_world
    ahead = _said(_facts(w, "Harbor Gate", ("Anvil", "Balm", "Needle"), ("Gale", "Rook", "Kite")))
    assert ahead["matchup.net_edges"] == (
        "board net matchup: 3 blue answer-edges into red vs 1 red into blue (+2) - the draft"
        " is ahead")
    assert ahead["matchup.tempo_diff"] == (
        "tempo war: blue median cooldown 7s vs red 9s - blue re-engages first; force fight"
        " frequency")
    assert ahead["matchup.barrier_need"] == (
        "barrier war: red fields 1200 barrier hp against 0 barrier-piercers on blue")
    assert ahead["matchup.antiheal_need"] == (
        "sustain war: red supports peak 70 heal against 0 anti-heal picks on blue")
    assert ahead["matchup.style_lean_red"] == "style war: red leans brawl, blue leans dive"
    behind = _said(_facts(w, "Harbor Gate", ("Gale", "Kite", "Rook"),
                          ("Anvil", "Mortar", "Needle", "Flint", "Balm", "Myrrh")))
    assert behind["matchup.net_edges"].endswith(
        "(-1) - the draft is behind; the open slots must swing it")
    assert behind["matchup.range_diff"] == (
        "poke war: blue median reach 30m vs red 20m - blue outranges; open fights at distance")
    even = _said(_facts(w, None, ("Tansy", "Sorrel"), ("Tansy", "Sorrel")))
    assert even["matchup.burst_vs_heal"].endswith(
        "90 vs red's best save 90 - their saves absorb the burst; stack or poke instead")
    assert even["matchup.heal_vs_burst"].endswith("90 - blue's saves keep pace")
    assert even["matchup.tempo_diff"].endswith("14s vs red 14s - even tempo")
    assert even["matchup.range_diff"].endswith("45m vs red 45m - even reach")
    assert "matchup.barrier_need" not in even and "matchup.style_lean_red" not in even


def test_a_count_reads_as_a_sentence():
    assert team_facts._count(1) == "1 pick" and team_facts._count(0) == "0 picks"
    assert team_facts._count(3, "flyer") == "3 flyers"
