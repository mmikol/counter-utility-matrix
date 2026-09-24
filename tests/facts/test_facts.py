"""A board's facts from the built database: the wording on real maps and
heroes, the terrain and stage facts, the map-rate and best-map facts and the
provenance. The values here are the scrape's, pinned on purpose; the
arithmetic behind them runs on the synthetic World in test_team.py,
test_metrics.py, test_tables.py, test_board_facts.py, test_hero_facts.py and
test_team_facts.py, and what the load itself reads is test_world.py's,
test_world_kits.py's and test_world_maps.py's."""

import statistics

import pytest

from facts import board_facts, compute, model
from facts.compute import STAGE_FEATURES, STAGE_MENTIONS, TERRAIN_STANDOUT
from facts.draft import Draft
from inference.result import _cited_fact

pytestmark = pytest.mark.invariant


def test_every_metric_a_strategy_can_name_reaches_the_fact_that_states_it(world):
    """The citation path, end to end: for every registered team, enemy and
    matchup metric, either a board fact states it or none does - and the ones
    that do are found by the metric's own name."""
    fs = board_facts.generate(world, Draft("King's Row", ("Zarya", "Pharah"),
                                           ("Ana", "Reinhardt")))
    metrics = [k for k in compute.registry() if k.startswith(("team.", "enemy.", "matchup."))]
    cited = [k for k in metrics if _cited_fact(fs, [k]) is not None]
    assert len(cited) > 60, len(cited)
    for key in cited:
        assert _cited_fact(fs, [key]).text


def test_every_named_hero_gets_a_deep_stack_of_independent_facts(world):
    fs = board_facts.generate(world, Draft("King's Row", ("Tracer",), ("Ana",)))
    for hero in ("Tracer", "Ana"):
        assert sum(1 for f in fs.facts if f.subject == hero) >= 80, hero
    # unnamed heroes get no itemised dump - depth is opt-in by selection
    assert sum(1 for f in fs.facts if f.subject == "Zarya") == 0


def test_the_whole_database_becomes_facts(world):
    fs = board_facts.generate(world, Draft("King's Row", ("Zarya",), ("Ana",)))
    keys = {f.key for f in fs.facts}
    assert {"hero.perk_effect", "playbook.catalog"} <= keys, keys
    # one population of rates, Blizzard's: no source's second set, no third party named
    assert "hero.rate_alt" not in keys and not hasattr(world.hero("Ana"), "alt_rates")
    assert {s["source"] for s in world.snapshots} == {"blizzard"}
    assert not any("counterpick" in f.text.lower() for f in fs.facts)
    assert any("Americas" in f.text for f in fs.facts if f.key == "meta.snapshot")


def test_the_rates_half_of_a_maps_style_is_derived_from_its_rates(world):
    """Map.rate_lift[S] is the z-score, across the maps, of the mean map-minus-overall
    win rate of the released heroes tagged S, each weighted 1/(its tag count)."""
    styles = sorted({s for h in world.heroes.values() for s in h.styles})
    assert styles and all(set(m.styles) == set(styles) for m in world.maps.values())

    def lift(m, style):
        rows = [((h.map_win(m.id) - h.win) / len(h.styles), 1 / len(h.styles))
                for h in world.heroes.values()
                if h.released and style in h.styles and h.win is not None
                and h.map_win(m.id) is not None]
        return sum(x for x, _ in rows) / sum(w for _, w in rows)
    for style in styles:
        lifts = {m.id: lift(m, style) for m in world.maps.values()}
        mean, sd = statistics.fmean(lifts.values()), statistics.pstdev(lifts.values())
        for m in world.maps.values():
            assert m.rate_lift[style] == pytest.approx((lifts[m.id] - mean) / sd, abs=1e-3)
            assert m.styles[style][1] is None
        assert statistics.fmean(m.rate_lift[style] for m in world.maps.values()) == \
            pytest.approx(0, abs=1e-3)
    m = world.map("King's Row")
    ranked = sorted(m.styles, key=lambda s: (-m.styles[s][0], s))
    assert m.style_top == ranked[0]
    assert m.style_margin == pytest.approx(m.styles[ranked[0]][0] - m.styles[ranked[1]][0])
    fs = board_facts.generate(world, Draft("King's Row"))
    facts = fs.find("map.rate_lift")
    assert [f.value["style"] for f in facts] == ranked
    top, lead = facts[0], m.rate_lift[ranked[0]]
    assert top.source == "playstyle+map_meta" and top.text == (
        "%s heroes win %.1f sd %s on King's Row than on other maps"
        % (ranked[0], abs(lead), "less" if lead < 0 else "more"))
    assert not any("authored" in f.text or "archetype" in f.text for f in fs.facts)


def test_a_map_without_text_gets_no_terrain_fact(world):
    bare = next(m for m in world.maps.values() if not m.terrain)
    fs = board_facts.generate(world, Draft(bare.name))
    assert fs.find("map.terrain_unread") and not fs.find("map.terrain")
    assert not fs.find("map.terrain_lean")
    assert "no terrain" in fs.find("map.style_top")[0].text


def test_terrain_and_both_halves_of_the_style_are_facts(world):
    m = world.map("King's Row")
    fs = board_facts.generate(world, Draft("King's Row"))
    standouts = sorted((f for f in model.TERRAIN_FEATURES
                        if abs(m.terrain_z[f]) >= TERRAIN_STANDOUT),
                       key=lambda f: (-abs(m.terrain_z[f]), f))
    facts = fs.find("map.terrain")
    assert [f.value["feature"] for f in facts] == standouts and standouts[0] == "chokes"
    assert facts[0].source == "map_terrain" and facts[0].text == (
        "King's Row: chokes, %.1f sd above the ordinary map (the wiki's article)"
        % m.terrain_z["chokes"])
    assert facts[0].value == {"feature": "chokes", "z": m.terrain_z["chokes"],
                              "per_thousand": m.terrain["chokes"]}
    ranked = sorted(m.styles, key=lambda s: (-m.styles[s][0], s))
    assert [f.value["style"] for f in fs.find("map.style")] == ranked
    assert {f.value["style"]: f.value["score"] for f in fs.find("map.terrain_lean")} == \
        m.terrain_lean
    for f in fs.find("map.style"):
        style = f.value["style"]
        assert f.value["terrain"] == m.terrain_lean[style]
        assert f.value["rates"] == m.rate_lift[style]
        assert f.text == "%s on King's Row: %+.1f sd (terrain %+.1f, rates %+.1f)" % (
            style, m.styles[style][0], m.terrain_lean[style], m.rate_lift[style])
    top = fs.find("map.style_top")[0]
    assert top.value == m.style_top and top.text.startswith(
        "King's Row rewards %s: terrain %+.1f, rates %+.1f ("
        % (m.style_top, m.terrain_lean[m.style_top], m.rate_lift[m.style_top]))


def test_a_map_lists_its_stages_as_arenas_or_as_the_phases_of_a_route(world):
    # one list fact a map: stages on arenas, phases on a route, neither without rows
    for name, key, other in (("Ilios", "map.stages", "map.phases"),
                             ("Havana", "map.phases", "map.stages"),
                             ("King's Row", "map.phases", "map.stages")):
        fs = board_facts.generate(world, Draft(name))
        assert fs.find(key)[0].value == world.map(name).stages and not fs.find(other)
        assert fs.find(key)[0].source == "map_stages"
    assert board_facts.generate(world, Draft("Havana")).find("map.phases")[0].text == \
        "Havana phases, in order: City Streets, Distillery, Sea Fort"
    fs = board_facts.generate(world, Draft("Colosseo"))
    assert not fs.find("map.stages") and not fs.find("map.phases")


def test_a_stage_fact_names_the_terrain_its_own_text_stresses(world):
    ilios = world.map("Ilios")
    z = ilios.stage_z["Well"]["hazards"]
    mentions = ilios.stage_terrain["Well"]["hazards"][1]
    assert z >= TERRAIN_STANDOUT and mentions >= STAGE_MENTIONS
    assert compute.stage_standouts(ilios, "Well") == [("hazards", z)]
    facts = board_facts.generate(world, Draft("Ilios")).find("map.stage_terrain")
    assert [f.value["stage"] for f in facts] == ["Well"]   # the article describes no other
    assert facts[0].source == "stage_terrain" and facts[0].text == (
        "Ilios - Well: hazards, %.1f sd above the ordinary stage (%d mentions in the wiki's"
        " article)" % (z, mentions))
    assert facts[0].value["features"] == [{
        "feature": "hazards", "z": z, "mentions": mentions,
        "per_thousand": ilios.stage_terrain["Well"]["hazards"][0]}]
    # every stage fact: above the ordinary stage, on two mentions or more, two features at most
    for m in world.maps.values():
        facts = board_facts.generate(world, Draft(m.name)).find("map.stage_terrain")
        assert [f.value["stage"] for f in facts] == [
            s for s in m.stages if compute.stage_standouts(m, s)], m.name
        for f in facts:
            named = f.value["features"]
            assert 1 <= len(named) <= STAGE_FEATURES
            assert [x["z"] for x in named] == sorted((x["z"] for x in named), reverse=True)
            assert all(x["z"] >= TERRAIN_STANDOUT and x["mentions"] >= STAGE_MENTIONS
                       for x in named)
    # a Hybrid phase's attack and defense text count together: one fact a phase
    assert [f.value["stage"] for f in board_facts.generate(world, Draft("King's Row")).find(
        "map.stage_terrain")] == ["Assault", "Escort"]


def test_a_stage_without_text_of_its_own_gets_no_stage_fact(world):
    oasis, dorado = world.map("Oasis"), world.map("Dorado")
    assert oasis.stages and not oasis.stage_terrain and not oasis.stage_z
    assert not dorado.stages and not dorado.stage_terrain
    for m in (oasis, dorado, world.map("Colosseo"), world.map("Blizzard World")):
        assert not board_facts.generate(world, Draft(m.name)).find("map.stage_terrain"), m.name
        assert all(compute.stage_standouts(m, s) == [] for s in m.stages)
    assert board_facts.generate(world, Draft("Oasis")).find("map.stages")  # the list still stands


def test_map_rates_are_the_intersection_with_the_board(world):
    """With a map, a hero's rate facts are about that map alone; without
    one, a single line of where the hero does best - never a line per map."""
    with_map = board_facts.generate(world, Draft("King's Row", ("Sombra",), ("Ana",)))
    assert not with_map.find("hero.rate_map") and not with_map.find("hero.rate_maps")
    assert len(with_map.find("hero.map_win", "Sombra")) == 1
    assert any("King's Row (this map)" in f.text for f in with_map.find("hero.map_win", "Sombra"))
    no_map = board_facts.generate(world, Draft(None, ("Sombra",), ("Ana",)))
    best = no_map.find("hero.rate_maps", "Sombra")
    assert len(best) == 1 and len(best[0].value) <= 3
    assert best[0].text.startswith("Sombra's best maps: ")
    assert len(no_map.find("hero.best_map", "Sombra")) <= 1 and not with_map.find("hero.best_map")
    assert not no_map.find("hero.map_win")


def test_a_heros_best_maps_are_derived_from_blizzards_map_rates(world):
    """Hero.best_maps: the three maps with the largest (map win rate - overall win
    rate), only where positive, ties by map name."""
    for h in world.heroes.values():
        lifts = sorted((-round(win - h.win, 3), world.maps[mid].name, mid)
                       for mid, (win, _) in h.map_rates.items()
                       if h.win is not None and win > h.win)
        assert h.best_maps == [mid for _, _, mid in lifts[:3]], h.name
        assert len(h.best_maps) <= 3
        assert all(h.map_win(mid) > h.win for mid in h.best_maps), h.name
    assert sum(1 for h in world.heroes.values() if h.released and len(h.best_maps) == 3) > 40
    assert all(not h.best_maps for h in world.heroes.values() if not h.map_rates)
    # the hero's own line without a map; on its best map, the rank, and the team's count
    sym = world.hero("Symmetra")
    top = world.maps[sym.best_maps[0]]
    line = board_facts.generate(world, Draft(blue=("Symmetra",))).find("hero.best_map",
                                                                       "Symmetra")[0]
    assert line.text.startswith("Symmetra's three best maps by Blizzard's map rates")
    assert line.value == [world.maps[mid].name for mid in sym.best_maps]
    assert line.source == "derived:hero.best_map"
    on_map = board_facts.generate(world, Draft(top.name, (), ("Symmetra",)))
    assert on_map.find("hero.map_strategy", "Symmetra")[0].value == 1
    assert any(f.value == "Symmetra" for f in on_map.find("map.playbook_pick"))


def test_the_provenance_is_one_line_per_source(world):
    fs = board_facts.generate(world, Draft("Ilios", (), ("Ana",)))
    lines = fs.find("meta.snapshot")
    seen = [(f.value["source"], f.value["queue"]) for f in lines]
    assert len(seen) == len(set(seen)), seen                  # no source and queue twice
    assert any(f.value["source"] == "blizzard" for f in lines)   # the main rates' line is there


def test_the_map_fact_carries_this_maps_ban_rate(world):
    fs = board_facts.generate(world, Draft("King's Row", ("Zarya",), ("Sombra", "Ana")))
    fact = fs.find("hero.map_win", "Sombra")[0]
    if world.hero("Sombra").map_ban(world.map("King's Row").id) is not None:
        assert ", banned " in fact.text
