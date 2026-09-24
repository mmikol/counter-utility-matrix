"""The UI layer: facts for a board, from the built database."""

import pytest

from db import Refusal
from ui.facts import compute, engine, model, tables
from ui.facts.draft import EXPECTED_SHAPE, TEAM_SIZE, is_sided
from ui.facts.team import TEAM_METRICS, team_metrics

pytestmark = pytest.mark.invariant


def test_every_metric_a_strategy_can_name_reaches_the_fact_that_states_it(world):
    """The citation path, end to end: for every registered team and matchup
    metric, either a board fact states it or none does - and the ones that do
    are found by the metric's own name."""
    from inference import engine
    from ui.facts import compute
    from ui.facts import engine as facts_engine
    fs = facts_engine.generate(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"],
                               [], "")
    metrics = [k for k in compute.registry() if k.startswith(("team.", "matchup."))]
    cited = [k for k in metrics if engine._cited_fact(fs, [k]) is not None]
    assert len(cited) > 60, len(cited)
    for key in cited:
        assert engine._cited_fact(fs, [key]).text


def test_every_fact_is_keyed_and_the_meta_comes_first(world):
    fs = engine.generate(world, "King's Row", ["Zarya", "Pharah"], ["Ana"])
    assert all(f.key and f.scope and f.text for f in fs.facts)
    assert fs.facts[0].scope == "meta"
    assert {"map", "hero", "team", "matchup", "playbook"} <= {f.scope for f in fs.facts}


def test_every_named_hero_gets_a_deep_stack_of_independent_facts(world):
    fs = engine.generate(world, "King's Row", ["Tracer"], ["Ana"])
    for hero in ("Tracer", "Ana"):
        assert sum(1 for f in fs.facts if f.subject == hero) >= 80, hero
    # unnamed heroes get no itemised dump - depth is opt-in by selection
    assert sum(1 for f in fs.facts if f.subject == "Zarya") == 0


def _an_edge(world):
    """(loser, winner): the first directed counter edge between released heroes, by name -
    the edges are the wiki's and move with it, so no test names one."""
    names = {h.id: h.name for h in world.heroes.values() if h.released}
    return min((names[a], names[b]) for a, b in world.counters if a in names and b in names)


def test_team_facts_appear_per_side_and_matchup_only_with_both(world):
    fs = engine.generate(world, "King's Row", ["Zarya", "Pharah"], [])
    scopes = {f.scope for f in fs.facts}
    assert "team" in scopes and "matchup" not in scopes
    assert fs.find("team.tanks", "red")
    fs = engine.generate(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"])
    assert fs.find("team.coverage", "blue") and fs.find("matchup.net_edges")
    # the crowd-control line names every blue pick that carries a tool, read off the picks
    (cc,) = fs.find("team.cc_count", "blue")
    tooled = [h for h in (world.hero("Ana"), world.hero("Reinhardt")) if h.cc_tools]
    assert tooled and all("%s: " % h.name in cc.text for h in tooled)
    loser, winner = _an_edge(world)                # whichever match-up the wiki states
    fs = engine.generate(world, "King's Row", [loser], [winner])
    assert any("%s is answered by blue %s" % (loser, winner) in f.text for f in fs.facts)


def test_board_context_facts_warn_and_cite(world):
    loser, winner = _an_edge(world)
    fs = engine.generate(world, None, [winner], [loser])
    assert any(f.text.startswith("WARNING: blue %s is answered by red %s" % (loser, winner))
               for f in fs.facts)
    fs = engine.generate(world, "King's Row", [], ["Ana", "Reinhardt"])
    assert any(f.key == "hero.with_ally" and f.subject == "Ana" for f in fs.facts)
    assert fs.find("hero.map_win", "Ana")


def test_metrics_cover_the_registry_exactly(world):
    m = world.map("King's Row")
    ns = compute.namespace(world, m, [world.hero("Zarya"), world.hero("Pharah")],
                           [world.hero("Ana"), world.hero("Reinhardt")], ban_count=0)
    team_keys = {k for k in ns["team"] if not k.startswith("_")}
    assert team_keys == set(TEAM_METRICS)
    assert set(ns["matchup"]) == set(compute.MATCHUP_METRICS)
    assert set(ns["map"]) == set(compute.MAP_METRICS)
    assert ns["team"]["tanks"] == 1 and ns["team"]["supports"] == 1
    assert ns["enemy"]["flyers"] == 1                     # Pharah
    # a flying tank is a flier, not one hitscan is picked to answer
    dva, pharah = world.hero("D.Va"), world.hero("Pharah")
    red = team_metrics(world, [dva, pharah])
    assert red["flyers"] == 2 and red["light_flyers"] == 1
    assert compute.red_matchup(red)["flyers"] == 1
    assert compute.red_matchup(team_metrics(world, [dva]))["flyers"] == 0
    assert compute.registry()["matchup.flyers"] == "red picks that fly, tanks aside"
    assert ns["team"]["coverage"] >= 1                    # Reinhardt answers Zarya
    for key in compute.TEXT_METRICS:
        prefix, name = key.split(".")
        assert name in ns[prefix if prefix != "enemy" else "team"]
    # the solver builds its bag lean: every key a strategy can name reads the same there
    blue = [world.hero("Ana"), world.hero("Reinhardt")]
    red = [world.hero("Zarya"), world.hero("Pharah")]
    full = team_metrics(world, blue, m, red)
    lean = team_metrics(world, blue, m, red, lean=True)
    for key in compute.registry():
        if key.startswith("team."):
            name = key.split(".", 1)[1]
            assert lean[name] == full[name], key


def test_metrics_without_a_map_fall_back_honestly(world):
    ns = compute.namespace(world, None, [], [world.hero("Ana")], ban_count=0)
    assert ns["map"]["known"] == 0 and ns["team"]["map_known"] == 0
    assert ns["team"]["map_win_mean"] == ns["team"]["win_mean"]
    assert ns["team"]["coverage_share"] == 0.0 and ns["matchup"]["chew_time_ours"] == 999.0


def test_the_whole_database_becomes_facts(world):
    # what the load itself reads is checked in test_world.py
    fs = engine.generate(world, "King's Row", ["Zarya"], ["Ana"])
    keys = {f.key for f in fs.facts}
    assert {"hero.perk_effect", "playbook.catalog"} <= keys, keys
    # one population of rates, Blizzard's: no source's second set, no third party named
    assert "hero.rate_alt" not in keys and not hasattr(world.hero("Ana"), "alt_rates")
    assert {s["source"] for s in world.snapshots} == {"blizzard"}
    assert not any("counterpick" in f.text.lower() for f in fs.facts)
    assert any("Americas" in f.text for f in fs.facts if f.key == "meta.snapshot")


def test_bans_become_facts_and_a_banned_pick_is_refused(world):
    fs = engine.generate(world, "King's Row", ["Zarya", "Pharah"], ["Ana"],
                         bans=["Widowmaker", "Sombra"])
    assert fs.bans == ["Widowmaker", "Sombra"]
    assert fs.find("bans.count") and len(fs.find("bans.hero")) == 2
    # Widowmaker answers Pharah and Zarya: the ban took an answer off the table
    assert any("banned Widowmaker answered red" in f.text for f in fs.facts)
    with pytest.raises(Refusal, match="banned this match"):
        engine.generate(world, None, ["Zarya"], ["Ana"], bans=["Ana"])
    with pytest.raises(Refusal, match="unknown heroes"):
        engine.generate(world, None, [], [], bans=["Goku"])


def test_the_rates_half_of_a_maps_style_is_derived_from_its_rates(world):
    """Map.rate_lift[S] is the z-score, across the maps, of the mean map-minus-overall
    win rate of the released heroes tagged S, each weighted 1/(its tag count)."""
    import statistics
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
    # an announced hero moves no map's style
    early = [h for h in world.heroes.values() if not h.released]
    before = {mm.id: (dict(mm.styles), dict(mm.rate_lift)) for mm in world.maps.values()}
    kept = [(h, h.win, h.map_rates) for h in early]
    for h in early:
        h.win, h.map_rates = 99.0, {m.id: (1.0, None)}
    try:
        tables.map_styles(world)
        assert early and before == {mm.id: (dict(mm.styles), dict(mm.rate_lift))
                                    for mm in world.maps.values()}
    finally:
        for h, win, map_rates in kept:
            h.win, h.map_rates = win, map_rates
    fs = engine.generate(world, "King's Row", [], [])
    facts = fs.find("map.rate_lift")
    assert [f.value["style"] for f in facts] == ranked
    top = facts[0]
    assert top.source == "playstyle+map_meta" and top.text == (
        "%s heroes win %.1f sd %s on King's Row than on other maps"
        % (ranked[0], abs(m.rate_lift[ranked[0]]),
           "less" if m.rate_lift[ranked[0]] < 0 else "more"))
    assert not any("authored" in f.text or "archetype" in f.text for f in fs.facts)


def test_a_map_without_text_reads_zero_for_every_terrain_metric(world):
    bare = [m for m in world.maps.values() if not m.terrain]
    assert bare
    for m in bare:
        metrics = compute.map_metrics(m, ban_count=0)
        assert all(metrics[f] == 0.0 for f in model.TERRAIN_FEATURES)
        assert m.terrain_lean == {}
        assert {s: v[0] for s, v in m.styles.items()} == m.rate_lift    # the rates alone
    none = compute.map_metrics(None, ban_count=0)
    assert all(none[f] == 0.0 for f in model.TERRAIN_FEATURES)
    fs = engine.generate(world, bare[0].name, [], [])
    assert fs.find("map.terrain_unread") and not fs.find("map.terrain")
    assert not fs.find("map.terrain_lean")
    assert "no terrain" in fs.find("map.style_top")[0].text


def test_terrain_and_both_halves_of_the_style_are_facts(world):
    from ui.facts.compute import TERRAIN_STANDOUT
    m = world.map("King's Row")
    fs = engine.generate(world, "King's Row", [], [])
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


def test_map_stages_counts_arenas_and_map_phases_counts_parts_of_a_route(world):
    """`map.stages >= 3` guards rules about separate arenas (Control, Flashpoint):
    a Hybrid map's two phases and an Escort map's three stretches count as
    map.phases and leave map.stages at 0."""
    for m in world.maps.values():
        x = compute.map_metrics(m, ban_count=0)
        assert (x["stages"], x["phases"]) == (
            (0, len(m.stages)) if is_sided(m) else (len(m.stages), 0)), m.name
        assert (x["stages"] >= 3) == (m.mode in ("Control", "Flashpoint")), m.name
    assert compute.map_metrics(world.map("Havana"), ban_count=0)["phases"] == 3
    assert compute.map_metrics(world.map("King's Row"), ban_count=0)["phases"] == 2
    assert compute.map_metrics(world.map("Dorado"), ban_count=0)["phases"] == 0
    none = compute.map_metrics(None, ban_count=0)
    assert (none["stages"], none["phases"]) == (0, 0)
    assert {"map.stages", "map.phases"} <= set(compute.registry())
    assert not {"map.stages", "map.phases"} & compute.TEXT_METRICS
    # one list fact a map: stages on arenas, phases on a route, neither without rows
    for name, key, other in (("Ilios", "map.stages", "map.phases"),
                             ("Havana", "map.phases", "map.stages"),
                             ("King's Row", "map.phases", "map.stages")):
        fs = engine.generate(world, name)
        assert fs.find(key)[0].value == world.map(name).stages and not fs.find(other)
        assert fs.find(key)[0].source == "map_stages"
    assert engine.generate(world, "Havana").find("map.phases")[0].text == \
        "Havana phases, in order: City Streets, Distillery, Sea Fort"
    fs = engine.generate(world, "Colosseo")
    assert not fs.find("map.stages") and not fs.find("map.phases")


def test_a_stage_fact_names_the_terrain_its_own_text_stresses(world):
    from ui.facts.compute import STAGE_FEATURES, STAGE_MENTIONS, TERRAIN_STANDOUT
    ilios = world.map("Ilios")
    z = ilios.stage_z["Well"]["hazards"]
    mentions = ilios.stage_terrain["Well"]["hazards"][1]
    assert z >= TERRAIN_STANDOUT and mentions >= STAGE_MENTIONS
    assert compute.stage_standouts(ilios, "Well") == [("hazards", z)]
    facts = engine.generate(world, "Ilios").find("map.stage_terrain")
    assert [f.value["stage"] for f in facts] == ["Well"]   # the article describes no other
    assert facts[0].source == "stage_terrain" and facts[0].text == (
        "Ilios - Well: hazards, %.1f sd above the ordinary stage (%d mentions in the wiki's"
        " article)" % (z, mentions))
    assert facts[0].value["features"] == [{
        "feature": "hazards", "z": z, "mentions": mentions,
        "per_thousand": ilios.stage_terrain["Well"]["hazards"][0]}]
    # every stage fact: above the ordinary stage, on two mentions or more, two features at most
    for m in world.maps.values():
        facts = engine.generate(world, m.name).find("map.stage_terrain")
        assert [f.value["stage"] for f in facts] == [
            s for s in m.stages if compute.stage_standouts(m, s)], m.name
        for f in facts:
            named = f.value["features"]
            assert 1 <= len(named) <= STAGE_FEATURES
            assert [x["z"] for x in named] == sorted((x["z"] for x in named), reverse=True)
            assert all(x["z"] >= TERRAIN_STANDOUT and x["mentions"] >= STAGE_MENTIONS
                       for x in named)
    # a Hybrid phase's attack and defense text count together: one fact a phase
    assert [f.value["stage"] for f in engine.generate(world, "King's Row").find(
        "map.stage_terrain")] == ["Assault", "Escort"]


def test_a_stage_without_text_of_its_own_gets_no_stage_fact(world):
    oasis, dorado = world.map("Oasis"), world.map("Dorado")
    assert oasis.stages and not oasis.stage_terrain and not oasis.stage_z
    assert not dorado.stages and not dorado.stage_terrain
    for m in (oasis, dorado, world.map("Colosseo"), world.map("Blizzard World")):
        assert not engine.generate(world, m.name).find("map.stage_terrain"), m.name
        assert all(compute.stage_standouts(m, s) == [] for s in m.stages)
    assert engine.generate(world, "Oasis").find("map.stages")     # the list still stands
    # one mention swings a short text's rate: it is not a fact
    import copy
    m = copy.copy(oasis)
    m.stage_terrain = {"Gardens": {"hazards": (40.0, compute.STAGE_MENTIONS - 1)}}
    m.stage_z = {"Gardens": {"hazards": 3.0}}
    assert compute.stage_standouts(m, "Gardens") == []
    m.stage_terrain = {"Gardens": {"hazards": (40.0, compute.STAGE_MENTIONS)}}
    assert compute.stage_standouts(m, "Gardens") == [("hazards", 3.0)]
    assert compute.stage_standouts(m, "University") == []


def test_sides_exist_only_on_escort_and_hybrid(world):
    from ui.facts.compute import map_metrics
    from ui.facts.draft import opposite
    kings, ilios = world.map("King's Row"), world.map("Ilios")
    assert is_sided(kings) and not is_sided(ilios)
    assert map_metrics(kings, "attack", ban_count=0)["side"] == "attack"
    assert map_metrics(ilios, "attack", ban_count=0)["side"] == ""
    assert map_metrics(ilios, ban_count=0)["sided"] == 0
    assert opposite("attack") == "defense" and opposite("") == ""
    fs = engine.generate(world, "King's Row", ["Zarya"], ["Ana"], side="attack")
    assert fs.side == "attack"
    assert any(f.key == "map.side" and "blue attacks King's Row; red defends" in f.text
               for f in fs.facts)
    assert fs.find("map.side_caveat")
    fs = engine.generate(world, "Ilios", [], [], side="attack")
    assert fs.side == "" and any("no attacking or defending side" in f.text for f in fs.facts)
    with pytest.raises(Refusal, match="side must be"):
        engine.generate(world, "King's Row", [], [], side="left")


def test_facts_are_the_authoritative_data_and_the_playbook_record_is_numbered_apart(world):
    # FACTS = INDEPENDENT ∪ DEPENDENT (F1..); the playbook's record rides below as S1..
    fs = engine.generate(world, "King's Row", ["Zarya", "Pharah"], ["Ana"])
    facts = [f for f in fs.facts if f.scope != engine.PLAYBOOK_SCOPE]
    side = fs.playbook
    assert facts and side
    assert all(f.id.startswith("F") for f in facts) and all(f.id.startswith("S") for f in side)
    assert [f.id for f in facts] == ["F%d" % i for i in range(1, len(facts) + 1)]
    assert [f.id for f in side] == ["S%d" % i for i in range(1, len(side) + 1)]
    assert {f.scope for f in facts} <= {"meta", "bans", "map", "hero", "team", "matchup"}
    assert {f.key.split(".")[0] for f in side} == {"playbook"}
    assert {f.key for f in side} == {"playbook.catalog"}
    assert fs.count == len(facts) and fs.to_dict()["playbook_count"] == len(side)
    text = fs.rendered()
    assert text.startswith("[F1]") and engine.PLAYBOOK_DIVIDER in text
    divider = text.index(engine.PLAYBOOK_DIVIDER)
    assert text.index("[S1]") > divider > text.index("[F%d]" % len(facts))
    catalog_note = next(f.text for f in side if f.key == "playbook.catalog")
    assert "STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS" in catalog_note


def test_map_rates_are_the_intersection_with_the_board(world):
    """With a map, a hero's rate facts are about that map alone; without
    one, a single line of where the hero does best - never a line per map."""
    with_map = engine.generate(world, "King's Row", ["Sombra"], ["Ana"])
    assert not with_map.find("hero.rate_map") and not with_map.find("hero.rate_maps")
    assert len(with_map.find("hero.map_win", "Sombra")) == 1
    assert any("King's Row (this map)" in f.text for f in with_map.find("hero.map_win", "Sombra"))
    no_map = engine.generate(world, None, ["Sombra"], ["Ana"])
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
    line = engine.generate(world, None, [], ["Symmetra"]).find("hero.best_map", "Symmetra")[0]
    assert line.text.startswith("Symmetra's three best maps by Blizzard's map rates")
    assert line.value == [world.maps[mid].name for mid in sym.best_maps]
    assert line.source == "derived:hero.best_map"
    on_map = engine.generate(world, top.name, [], ["Symmetra"])
    assert on_map.find("hero.map_strategy", "Symmetra")[0].value == 1
    assert any(f.value == "Symmetra" for f in on_map.find("map.playbook_pick"))
    assert team_metrics(world, [sym], top)["map_strategy_hits"] == 1
    assert compute.registry()["team.map_strategy_hits"] == (
        "picks whose three best maps by rate include this map")


def test_the_provenance_is_one_line_per_source(world):
    fs = engine.generate(world, "Ilios", [], ["Ana"])
    lines = fs.find("meta.snapshot")
    seen = [(f.value["source"], f.value["queue"]) for f in lines]
    assert len(seen) == len(set(seen)), seen                  # no source and queue twice
    assert any(f.value["source"] == "blizzard" for f in lines)   # the main rates' line is there


def test_the_map_fact_carries_this_maps_ban_rate_and_the_team_its_availability_here(world):
    fs = engine.generate(world, "King's Row", ["Zarya"], ["Sombra", "Ana"])
    fact = fs.find("hero.map_win", "Sombra")[0]
    if world.hero("Sombra").map_ban(world.map("King's Row").id) is not None:
        assert ", banned " in fact.text
    picks = [world.hero("Sombra"), world.hero("Ana")]
    t = team_metrics(world, picks, world.map("King's Row"), [])
    assert 0 <= t["map_availability"] <= 1
    anywhere = team_metrics(world, picks, None, [])
    assert anywhere["map_availability"] == anywhere["availability"]


def test_expected_picks_read_the_map_and_the_meta_and_no_strategy(world):
    """Red's likely six: their revealed picks first, then the most-picked
    heroes on the map, never a banned hero, never a third tank (the queue's
    own limit), the overall meta when no map is set - each with the rate
    it rests on. No strategy is read: the same six under any playbook."""
    from collections import Counter
    m = world.map("King's Row")
    zarya, sombra = world.hero("Zarya"), world.hero("Sombra")
    six = compute.expected_picks(world, m, revealed=[zarya], banned=[sombra])
    assert six[0]["hero"] == "Zarya" and six[0]["locked"] and six[0]["why"] == "revealed"
    assert len(six) == TEAM_SIZE and "Sombra" not in [p["hero"] for p in six]
    assert Counter(p["role"] for p in six) == EXPECTED_SHAPE      # a two-two-two
    rest = [p for p in six if not p["locked"]]
    assert all(p["why"].startswith("picked in ") and "King's Row" in p["why"] for p in rest
               if p["rate"] is not None)
    # deterministic
    assert six == compute.expected_picks(world, m, revealed=[zarya], banned=[sombra])
    # the synergies pull: a partner already on the six is named in the reason
    heroes = [world.hero(p["hero"]) for p in six]
    paired = any(world.synergy(x.id, y.id) for x in heroes for y in heroes if x is not y)
    assert paired == any("pairs with" in p["why"] for p in rest)
    anywhere = compute.expected_picks(world, None)
    assert Counter(p["role"] for p in anywhere) == EXPECTED_SHAPE
    assert all("overall" in p["why"] for p in anywhere if p["rate"] is not None)
    # no strategy is read: nothing here takes a catalog
    import inspect
    assert "catalog" not in inspect.signature(compute.expected_picks).parameters


@pytest.mark.invariant
def test_no_matchup_metric_restates_a_team_metric(world):
    """A matchup key must read both sides. One that copies blue's own number
    gives a second name to one signal: two strategies reading it through the
    two names weigh that signal twice, and nothing in the catalog shows it."""
    blue = [world.hero(n) for n in ("Reinhardt", "D.Va", "Ashe", "Sojourn", "Ana", "Kiriko")]
    red = [world.hero(n) for n in ("Winston", "Zarya", "Genji", "Tracer", "Lucio", "Mercy")]
    m = next(iter(world.maps.values()))
    blue_t = team_metrics(world, blue, m, red)
    red_t = team_metrics(world, red, m, blue)
    matchup = compute.matchup_metrics(blue_t, red_t)

    # a matchup key that equals blue's own is only proof of a copy if it also
    # moves when blue does and red does not: compare a second blue on one red
    other = [world.hero(n) for n in ("Orisa", "Ramattra", "Reaper", "Bastion", "Moira", "Brigitte")]
    other_t = team_metrics(world, other, m, red)
    other_matchup = compute.matchup_metrics(other_t, red_t)

    copies = [key for key, value in matchup.items()
              if key in blue_t and value == blue_t[key]
              and other_matchup.get(key) == other_t.get(key)]
    assert not copies, "matchup restates team: %s - read team.* instead" % ", ".join(sorted(copies))
