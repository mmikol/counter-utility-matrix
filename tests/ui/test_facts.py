"""The UI layer: facts for a board, from the built database."""

import pathlib

import pytest

from ui.facts import compute, engine, model

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


def test_world_loads_the_whole_roster_with_kit_numbers(world):
    assert len(world.heroes) > 40 and len(world.maps) >= 25
    ana = world.hero("Ana")
    assert ana.role == "support" and ana.hitscan
    # an ultimate's numbers are its own: Nano Boost's 250 is not Ana's healing,
    # Self-Destruct's 1000 not D.Va's burst, Transcendence not Zenyatta's rate,
    # Deadeye's lock-on not Cassidy's reach
    assert 75 <= ana.peak_heal < 250
    assert world.hero("D.Va").burst < 1000 <= world.hero("D.Va").ult_damage
    assert world.hero("Zenyatta").hps < 100
    assert 30 <= world.hero("Cassidy").max_range < world.hero("Widowmaker").max_range
    assert "Sleep Dart" in ana.cc_tools
    assert world.hero("Pharah").flyer and not world.hero("Reinhardt").flyer
    assert world.hero("Reinhardt").barrier_hp >= 1000
    assert world.hero("Kiriko").cleanse_tools
    assert world.heal_bench > 0


def test_kit_rows_are_read_in_their_own_units(world):
    # a percent is not hit points: lifesteal is a share, overhealth its published cap,
    # EMP a damage ultimate that adds no hit points
    reaper, mauga, sombra = world.hero("Reaper"), world.hero("Mauga"), world.hero("Sombra")
    assert reaper.self_heal == 0 and reaper.lifesteal == pytest.approx(0.3)
    assert mauga.peak_heal == 0 and mauga.self_hps == 0 and mauga.lifesteal == 1.0
    # an own heal that runs for a duration is also a cast: a share of the held rate
    # for Overdrive's 3 s, a rate for its longest duration, "100 over 3 seconds".
    # A passive's share has no duration; Siphon Blaster heals off its own damage
    assert mauga.self_heal == pytest.approx(mauga.dps * 3.0)
    assert world.hero("Junker Queen").self_heal == 100 and world.hero("Mei").self_heal == 250
    assert world.hero("Roadhog").self_heal == 450 and world.hero("Emre").self_heal == 30
    assert world.hero("Domina").self_heal == 0
    assert world.hero("Sigma").overhealth == 400 and mauga.overhealth == 150
    assert world.hero("Lifeweaver").overhealth == 100 == world.hero("Brigitte").overhealth
    assert sombra.dmg_ult and sombra.ult_damage == 0 and sombra.dmg_amp == 0
    assert compute.team_metrics(world, [reaper, mauga])["lifelines"] == 2
    # a sum, a volley and a window's total are not one hit or a rate
    hazard = world.hero("Hazard")
    assert hazard.burst == 75 and hazard.ult_damage == 90
    assert world.hero("Ramattra").burst == 65
    assert world.hero("Zenyatta").burst == 100 and world.hero("Widowmaker").burst >= 250
    assert compute.team_metrics(world, [world.hero("Zenyatta")])["one_shots"] == 0
    # an ultimate fired at its rate for its duration, under the roster's cap
    assert world.hero("Pharah").ult_damage == world.ult_cap
    assert 130 < world.hero("Venture").ult_damage < world.ult_cap
    # three charges of 180; a 175 heavy round on a 2.5 s cooldown, four in 8.8 s
    assert world.hero("Shion").ult_damage == 540
    assert world.hero("Emre").ult_damage == 700
    assert world.hero("Bastion").ult_damage == 550 and world.hero("Genji").ult_damage > 900
    # sustained rates: the reload in the row's text, the swing the rate counts,
    # the magazine's share where no reload figure is usable
    assert world.hero("Zenyatta").dps == pytest.approx(108.7)
    # both chainguns off one magazine: 138.88 for 8.64 s of every 10.64
    assert world.hero("Mauga").dps == pytest.approx(112.78, abs=0.01)
    assert world.hero("Mauga").hitscan_range == 40
    assert world.hero("Wuyang").dps == pytest.approx(128.21)
    assert world.hero("Vendetta").dps == pytest.approx(53.1)
    cat = world.hero("Jetpack Cat")
    assert cat.dps == pytest.approx(87.18, abs=0.01) and cat.hps == pytest.approx(cat.dps)


def test_the_weapon_a_hero_fights_with_sets_its_kind_and_reach(world):
    winston, torb, ramattra = (world.hero(n) for n in ("Winston", "Torbjörn", "Ramattra"))
    assert not winston.hitscan and winston.beam and winston.max_range == 8
    assert winston.burst == 60 and winston.pierces_barrier
    assert not torb.melee and not torb.pierces_barrier and torb.max_range == 0
    assert torb.self_heal == 0 and torb.self_hps == 0
    assert ramattra.melee and ramattra.pierces_barrier and ramattra.dps == 100
    assert ramattra.max_range == 0 and world.hero("Anran").max_range == 0
    # Nemesis Form's 275 armor for 8 s of every 16: the form's, not the base row's.
    # An ultimate's armor (Rally) stays out
    assert ramattra.form_armor == 137.5 and ramattra.armor == 100 and ramattra.pool == 375
    assert [h.name for h in world.heroes.values() if h.form_armor] == ["Ramattra"]
    t = compute.team_metrics(world, [ramattra])
    assert t["armor_total"] == 237.5 and t["pool_total"] == 512.5 and t["weakest"] == "Ramattra"
    assert t["armor_share"] == pytest.approx(237.5 / 512.5)
    assert world.hero("Mei").max_range == 12 and world.hero("Sojourn").max_range == 60
    dmon, dva = world.hero("D.Mon"), world.hero("D.Va")
    assert dmon.max_range == 4 and dmon.dps == pytest.approx(91.2) and dmon.ult_damage == 125
    assert dva.burst == 25 and dva.cc_tools == [] and dmon.cc_tools == ["Surging Strike"]
    # a healing beam is not a beam; a kick is not a barrier piercer
    assert not world.hero("Mercy").beam and not world.hero("Illari").beam
    assert world.hero("Moira").beam
    assert not world.hero("Zenyatta").pierces_barrier


def test_tools_are_counted_once_and_for_what_they_do(world):
    counts = {n: world.hero(n).aoe_count for n in
              ("Sigma", "Junkrat", "Pharah", "Freja", "Reinhardt", "Doomfist", "Mauga")}
    assert counts == {"Sigma": 3, "Junkrat": 4, "Pharah": 3, "Freja": 2, "Reinhardt": 1,
                      "Doomfist": 3, "Mauga": 3}
    assert world.hero("Baptiste").aoe_count == 3 and world.hero("Baptiste").aoe_damage == 0
    # a damaging piece typed Area of effect counts without the tag; a piece that
    # deals no damage (Defense Matrix, Kinetic Grasp) does not
    area = {n: (world.hero(n).aoe_count, world.hero(n).aoe_damage)
            for n in ("Sierra", "Orisa", "Emre", "Lúcio", "Jetpack Cat", "D.Va", "Sigma")}
    assert area == {"Sierra": (2, 2), "Orisa": (2, 2), "Emre": (3, 3), "Lúcio": (4, 1),
                    "Jetpack Cat": (3, 2), "D.Va": (2, 2), "Sigma": (3, 3)}
    assert world.hero("Junkrat").aoe_damage == 4
    assert world.hero("Soldier: 76").cc_tools == [] and world.hero("Emre").cc_tools == []
    assert "Concussion Mine" in world.hero("Junkrat").cc_tools
    assert world.hero("Sierra").mobility_tools == ["Anchor Drone"]
    # typed Movement with no movement tag; a speed buff alone is not one
    assert world.hero("Emre").mobility_tools == ["Siphon Blaster"]
    assert "Roll" in world.hero("Wrecking Ball").mobility_tools
    assert "Commanding Shout" not in world.hero("Junker Queen").mobility_tools
    assert "Nemesis Form" not in world.hero("Ramattra").mobility_tools
    assert sum(1 for h in world.heroes.values() if h.released and h.mobility_tools) == 39
    assert world.hero("Zarya").deployables == []
    assert world.hero("Baptiste").invuln_tools == ["Immortality Field"]
    doomfist = world.hero("Doomfist")
    assert doomfist.cleanse_tools == [] and doomfist.invuln_tools == []
    assert 2.5 not in world.hero("Emre").cooldowns
    # what lands on a teammate, apart from what saves only its owner
    picks = [world.hero(n) for n in ("Kiriko", "Reaper", "Venture", "Baptiste", "Mercy", "Moira")]
    t = compute.team_metrics(world, picks)
    assert t["cleanse"] == 4 and t["team_cleanse"] == 1            # Protection Suzu alone
    assert t["invuln"] == 6 and t["team_saves"] == 3               # Suzu, the Field, Resurrect
    assert world.hero("Zenyatta").team_cleanse_tools == ["Transcendence"]
    t = compute.team_metrics(world, [world.hero(n) for n in
                                     ("Reinhardt", "Ana", "Widowmaker", "Tracer", "Winston")])
    assert t["burst_max"] == 300 and t["burst_hero"] == "Reinhardt"
    assert t["burst_ranged"] == world.hero("Widowmaker").burst
    assert compute.team_metrics(world, [world.hero("Reinhardt")])["burst_ranged"] == 0
    assert t["hitscan"] == 3 and t["hitscan_reach"] == 1            # Widowmaker's 70 m
    # 30 m answers a flier (Shion's pistols), 25 m does not
    assert compute.FLIER_REACH == 30 and world.hero("Shion").hitscan_range == 30
    reach = compute.team_metrics(world, [world.hero(n) for n in
                                         ("Shion", "Wrecking Ball", "Junker Queen", "Cassidy")])
    assert reach["hitscan"] == 4 and reach["hitscan_reach"] == 2
    # an explosion does not crit: Freja's bolt is 35 to the head, 75 flat
    assert world.hero("Freja").burst == 75
    assert "enemy.team_saves" in compute.registry()


def test_an_announced_hero_sets_no_roster_wide_figure(world):
    import statistics
    out = [h for h in world.heroes.values() if h.released and h.role == "support"]
    assert world.heal_bench == 2 * statistics.median(h.peak_heal for h in out if h.peak_heal)
    assert world.hps_bench == 2 * statistics.median(h.hps for h in out if h.hps)
    assert world.ult_cap == max(h.ult_damage for h in world.heroes.values() if h.released)


def test_names_resolve_across_spellings(world):
    assert world.hero("lucio").name == "Lúcio"
    assert world.hero("D.VA").name == "D.Va"
    assert world.map("kings row").name == "King's Row"
    with pytest.raises(ValueError, match="unknown heroes"):
        world.resolve(None, ["Goku"], [])
    with pytest.raises(ValueError, match="unknown map"):
        world.resolve("Atlantis", [], [])


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
                           [world.hero("Ana"), world.hero("Reinhardt")])
    team_keys = {k for k in ns["team"] if not k.startswith("_")}
    assert team_keys == set(compute.TEAM_METRICS)
    assert set(ns["matchup"]) == set(compute.MATCHUP_METRICS)
    assert set(ns["map"]) == set(compute.MAP_METRICS)
    assert ns["team"]["tanks"] == 1 and ns["team"]["supports"] == 1
    assert ns["enemy"]["flyers"] == 1                     # Pharah
    # a flying tank is a flier, not one hitscan is picked to answer
    dva, pharah = world.hero("D.Va"), world.hero("Pharah")
    red = compute.team_metrics(world, [dva, pharah])
    assert red["flyers"] == 2 and red["light_flyers"] == 1
    assert compute.red_matchup(red)["flyers"] == 1
    assert compute.red_matchup(compute.team_metrics(world, [dva]))["flyers"] == 0
    assert compute.registry()["matchup.flyers"] == "red picks that fly, tanks aside"
    assert ns["team"]["coverage"] >= 1                    # Reinhardt answers Zarya
    for key in compute.TEXT_METRICS:
        prefix, name = key.split(".")
        assert name in ns[prefix if prefix != "enemy" else "team"]


def test_metrics_without_a_map_fall_back_honestly(world):
    ns = compute.namespace(world, None, [], [world.hero("Ana")])
    assert ns["map"]["known"] == 0 and ns["team"]["map_known"] == 0
    assert ns["team"]["map_win_mean"] == ns["team"]["win_mean"]
    assert ns["team"]["coverage_share"] == 0.0 and ns["matchup"]["chew_time_ours"] == 999.0


def test_the_whole_database_becomes_facts(world, rows):
    # every data table is read by the World (the ledger is not data)
    import re

    from ui.facts import model as model_module
    src = pathlib.Path(model_module.__file__).read_text(encoding="utf-8")
    unread = [t for (t,) in rows("select tablename from pg_tables where schemaname='public'")
              if t != "schema_migrations" and not re.search(r"\b%s\b" % t, src)]
    assert unread == [], unread
    fs = engine.generate(world, "King's Row", ["Zarya"], ["Ana"])
    keys = {f.key for f in fs.facts}
    assert {"hero.perk_effect", "playbook.catalog"} <= keys, keys
    # one population of rates, Blizzard's: no source's second set, no third party named
    assert "hero.rate_alt" not in keys and not hasattr(world.hero("Ana"), "alt_rates")
    assert {s["source"] for s in world.snapshots} == {"blizzard"}
    assert not any("counterpick" in f.text.lower() for f in fs.facts)
    assert "map_strategy" not in src and "counterpick" not in src
    assert any("Americas" in f.text for f in fs.facts if f.key == "meta.snapshot")


def test_bans_become_facts_and_a_banned_pick_is_refused(world):
    fs = engine.generate(world, "King's Row", ["Zarya", "Pharah"], ["Ana"],
                         bans=["Widowmaker", "Sombra"])
    assert fs.bans == ["Widowmaker", "Sombra"]
    assert fs.find("bans.count") and len(fs.find("bans.hero")) == 2
    # Widowmaker answers Pharah and Zarya: the ban took an answer off the table
    assert any("banned Widowmaker answered red" in f.text for f in fs.facts)
    with pytest.raises(ValueError, match="banned this match"):
        engine.generate(world, None, ["Zarya"], ["Ana"], bans=["Ana"])
    with pytest.raises(ValueError, match="unknown heroes"):
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
        model.map_styles(world)
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


def _with_text(world):
    return [m for m in world.maps.values() if m.terrain]


def test_terrain_metrics_are_z_scores_across_the_maps_with_text(world, rows):
    import statistics
    features = model.TERRAIN_FEATURES
    assert set(features) == {f for (f,) in rows("select distinct feature from map_terrain")}
    assert set(features) < set(compute.MAP_METRICS)
    assert not {"map." + f for f in features} & compute.TEXT_METRICS
    assert all("map." + f in compute.registry() for f in features)
    read = _with_text(world)
    assert len(read) == rows("select count(distinct map_id) from map_terrain")[0][0] >= 2
    for m in read:
        assert set(m.terrain) == set(features)             # all eight rows, zeros included
    for f in features:
        raw = {m.id: m.terrain[f] for m in read}
        mean, sd = statistics.fmean(raw.values()), statistics.pstdev(raw.values())
        assert sd > 0
        for m in read:
            assert m.terrain_z[f] == pytest.approx((raw[m.id] - mean) / sd, abs=1e-3)
            assert compute.map_metrics(m)[f] == m.terrain_z[f]
        zs = [m.terrain_z[f] for m in read]
        assert statistics.fmean(zs) == pytest.approx(0, abs=1e-3)
        assert statistics.pstdev(zs) == pytest.approx(1, abs=1e-2)
    # the wiki's King's Row: narrow streets and a first chokepoint
    kings = world.map("King's Row")
    assert max(features, key=lambda f: kings.terrain_z[f]) == "chokes"
    assert kings.terrain_z["chokes"] == max(m.terrain_z["chokes"] for m in read)


def test_a_map_without_text_reads_zero_for_every_terrain_metric(world):
    bare = [m for m in world.maps.values() if not m.terrain]
    assert bare
    for m in bare:
        metrics = compute.map_metrics(m)
        assert all(metrics[f] == 0.0 for f in model.TERRAIN_FEATURES)
        assert m.terrain_lean == {}
        assert {s: v[0] for s, v in m.styles.items()} == m.rate_lift    # the rates alone
    none = compute.map_metrics(None)
    assert all(none[f] == 0.0 for f in model.TERRAIN_FEATURES)
    fs = engine.generate(world, bare[0].name, [], [])
    assert fs.find("map.terrain_unread") and not fs.find("map.terrain")
    assert not fs.find("map.terrain_lean")
    assert "no terrain" in fs.find("map.style_top")[0].text


def test_a_maps_style_is_the_rates_lift_plus_the_terrains_lean(world):
    import statistics
    assert model.TERRAIN_LEAN == {"brawl": ("chokes", "interiors"),
                                  "dive": ("high_ground", "flanks", "hazards"),
                                  "poke": ("sightlines", "open_ground")}
    read = _with_text(world)
    for style, features in model.TERRAIN_LEAN.items():
        means = {m.id: statistics.fmean(m.terrain_z[f] for f in features) for m in read}
        mean, sd = statistics.fmean(means.values()), statistics.pstdev(means.values())
        for m in read:
            assert m.terrain_lean[style] == pytest.approx((means[m.id] - mean) / sd, abs=1e-3)
        assert statistics.pstdev(m.terrain_lean[style] for m in read) == \
            pytest.approx(1, abs=1e-2)                       # on the rates' scale
    for m in world.maps.values():
        for style, (score, note) in m.styles.items():
            assert note is None and score == pytest.approx(
                m.rate_lift.get(style, 0.0) + m.terrain_lean.get(style, 0.0), abs=1e-3)
    # the wiki's chokes outweigh King's Row's rates: the terrain rectifies the style
    kings = world.map("King's Row")
    assert max(kings.terrain_lean, key=kings.terrain_lean.get) == "brawl"
    assert kings.style_top == max(kings.styles, key=lambda s: kings.styles[s][0])
    assert compute.map_metrics(kings)["style_top"] == kings.style_top
    assert compute.map_metrics(kings)["style_margin"] == kings.style_margin


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


def test_the_terrain_and_the_style_are_the_same_on_every_load(world, db):
    again = model.load(db)
    db.rollback()
    for m in world.maps.values():
        other = again.maps[m.id]
        assert (m.terrain, m.terrain_z, m.terrain_lean, m.rate_lift, m.styles) == (
            other.terrain, other.terrain_z, other.terrain_lean, other.rate_lift, other.styles)
        assert list(compute.map_metrics(m)) == list(compute.map_metrics(other))
    before = {m.id: (dict(m.terrain_z), dict(m.terrain_lean)) for m in world.maps.values()}
    model.map_terrain(world)
    assert before == {m.id: (dict(m.terrain_z), dict(m.terrain_lean))
                      for m in world.maps.values()}


def test_stages_are_read_per_mode_as_the_wiki_holds_them(world, rows):
    stored = {}
    for name, stage in rows("""select m.name, s.name from map_stages s join maps m
                               using(map_id) order by m.name, s.position"""):
        stored.setdefault(name, []).append(stage)
    assert {m.name: m.stages for m in world.maps.values() if m.stages} == stored
    by_mode = {}
    for m in world.maps.values():
        by_mode.setdefault(m.mode, []).append(m)
    assert all(len(m.stages) == 3 for m in by_mode["Control"])
    assert all(len(m.stages) == 5 for m in by_mode["Flashpoint"])
    assert all(m.stages == ["Assault", "Escort"] for m in by_mode["Hybrid"])   # point, then payload
    assert all(m.stages == [] for m in by_mode["Push"])
    # an Escort map holds the three stretches its own article names, or none
    assert {len(m.stages) for m in by_mode["Escort"]} == {0, 3}
    assert world.map("Havana").stages == ["City Streets", "Distillery", "Sea Fort"]
    assert world.map("Dorado").stages == []
    assert world.map("Ilios").stages == ["Lighthouse", "Well", "Ruins"]


def test_map_stages_counts_arenas_and_map_phases_counts_parts_of_a_route(world):
    """`map.stages >= 3` guards rules about separate arenas (Control, Flashpoint):
    a Hybrid map's two phases and an Escort map's three stretches count as
    map.phases and leave map.stages at 0."""
    for m in world.maps.values():
        x = compute.map_metrics(m)
        assert (x["stages"], x["phases"]) == (
            (0, len(m.stages)) if compute.is_sided(m) else (len(m.stages), 0)), m.name
        assert (x["stages"] >= 3) == (m.mode in ("Control", "Flashpoint")), m.name
    assert compute.map_metrics(world.map("Havana"))["phases"] == 3
    assert compute.map_metrics(world.map("King's Row"))["phases"] == 2
    assert compute.map_metrics(world.map("Dorado"))["phases"] == 0
    none = compute.map_metrics(None)
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


def test_stage_terrain_is_z_scored_across_the_stages_with_text(world, rows):
    import statistics
    features = model.TERRAIN_FEATURES
    read = [(m, stage) for m in world.maps.values() for stage in m.stage_terrain]
    assert len(read) == rows("select count(distinct stage_id) from stage_terrain")[0][0] >= 2
    for m, stage in read:
        assert stage in m.stages and set(m.stage_terrain[stage]) == set(features)
        assert set(m.stage_z[stage]) == set(features)
    for f in features:
        raw = [m.stage_terrain[stage][f][0] for m, stage in read]
        mean, sd = statistics.fmean(raw), statistics.pstdev(raw)
        for m, stage in read:
            assert m.stage_z[stage][f] == pytest.approx(
                (m.stage_terrain[stage][f][0] - mean) / sd if sd else 0.0, abs=1e-3)
    (rate, mentions), = rows("""select t.per_thousand, t.mentions from stage_terrain t
        join map_stages s using(stage_id) join maps m using(map_id)
        where m.name = 'Ilios' and s.name = 'Well' and t.feature = 'hazards'""")
    assert world.map("Ilios").stage_terrain["Well"]["hazards"] == (float(rate), mentions)
    # the same on every pass
    before = {m.id: {s: dict(z) for s, z in m.stage_z.items()} for m in world.maps.values()}
    model.stage_terrain(world)
    assert before == {m.id: m.stage_z for m in world.maps.values()}


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
    from ui.facts.compute import is_sided, map_metrics, opposite
    kings, ilios = world.map("King's Row"), world.map("Ilios")
    assert is_sided(kings) and not is_sided(ilios)
    assert map_metrics(kings, "attack")["side"] == "attack"
    assert map_metrics(ilios, "attack")["side"] == "" and map_metrics(ilios)["sided"] == 0
    assert opposite("attack") == "defense" and opposite("") == ""
    fs = engine.generate(world, "King's Row", ["Zarya"], ["Ana"], side="attack")
    assert fs.side == "attack"
    assert any(f.key == "map.side" and "blue attacks King's Row; red defends" in f.text
               for f in fs.facts)
    assert fs.find("map.side_caveat")
    fs = engine.generate(world, "Ilios", [], [], side="attack")
    assert fs.side == "" and any("no attacking or defending side" in f.text for f in fs.facts)
    with pytest.raises(ValueError, match="side must be"):
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
    assert compute.team_metrics(world, [sym], top)["map_strategy_hits"] == 1
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
    t = compute.team_metrics(world, picks, world.map("King's Row"), [])
    assert 0 <= t["map_availability"] <= 1
    anywhere = compute.team_metrics(world, picks, None, [])
    assert anywhere["map_availability"] == anywhere["availability"]


def test_expected_picks_read_the_map_and_the_meta_and_no_strategy(world):
    """Red's likely six: their revealed picks first, then the most-picked
    heroes on the map, never a banned hero, never a third tank (the queue's
    own limit), the overall meta when no map is set - each with the rate
    it rests on. No strategy is read: the same six under any playbook."""
    from collections import Counter
    m = world.map("King's Row")
    zarya, sombra = world.hero("Zarya"), world.hero("Sombra")
    six = compute.expected_picks(world, m, [zarya], [sombra])
    assert six[0]["hero"] == "Zarya" and six[0]["locked"] and six[0]["why"] == "revealed"
    assert len(six) == compute.TEAM_SIZE and "Sombra" not in [p["hero"] for p in six]
    assert Counter(p["role"] for p in six) == compute.EXPECTED_SHAPE      # a two-two-two
    rest = [p for p in six if not p["locked"]]
    assert all(p["why"].startswith("picked in ") and "King's Row" in p["why"] for p in rest
               if p["rate"] is not None)
    assert six == compute.expected_picks(world, m, [zarya], [sombra])      # deterministic
    # the synergies pull: a partner already on the six is named in the reason
    heroes = [world.hero(p["hero"]) for p in six]
    paired = any(world.synergy(x.id, y.id) for x in heroes for y in heroes if x is not y)
    assert paired == any("pairs with" in p["why"] for p in rest)
    anywhere = compute.expected_picks(world, None, [], [])
    assert Counter(p["role"] for p in anywhere) == compute.EXPECTED_SHAPE
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
    blue_t = compute.team_metrics(world, blue, m, red)
    red_t = compute.team_metrics(world, red, m, blue)
    matchup = compute.matchup_metrics(blue_t, red_t)

    # a matchup key that equals blue's own is only proof of a copy if it also
    # moves when blue does and red does not: compare a second blue on one red
    other = [world.hero(n) for n in ("Orisa", "Ramattra", "Reaper", "Bastion", "Moira", "Brigitte")]
    other_t = compute.team_metrics(world, other, m, red)
    other_matchup = compute.matchup_metrics(other_t, red_t)

    copies = [key for key, value in matchup.items()
              if key in blue_t and value == blue_t[key]
              and other_matchup.get(key) == other_t.get(key)]
    assert not copies, "matchup restates team: %s - read team.* instead" % ", ".join(sorted(copies))


@pytest.mark.invariant
def test_no_released_hero_is_missing_a_core_kit_number(world):
    """The kit block carries most of the playbook's weight, and a hole in it is
    silent: a tank that deals no damage still scores, just wrongly. Domina read
    zero because her beam publishes a rate only as damage `over time`."""
    holes = []
    for hero in sorted(world.heroes.values(), key=lambda h: h.name):
        if not hero.released:
            continue
        if not hero.pool:
            holes.append("%s has no health pool" % hero.name)
        if not hero.dps:
            holes.append("%s deals no damage" % hero.name)
        if hero.role == "support" and not hero.hps:
            holes.append("%s is a support that heals nothing" % hero.name)
    assert not holes, holes
