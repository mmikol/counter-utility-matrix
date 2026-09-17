"""The UI layer: facts for a board, from the built database."""

import pathlib

import pytest

from ui.facts import compute, engine, model

pytestmark = pytest.mark.invariant


@pytest.fixture(scope="module")
def world(db):
    w = model.load(db)
    db.rollback()
    return w


def test_world_loads_the_whole_roster_with_kit_numbers(world):
    assert len(world.heroes) > 40 and len(world.maps) >= 25
    ana = world.hero("Ana")
    assert ana.role == "support" and ana.peak_heal >= 250 and ana.hitscan
    assert "Sleep Dart" in ana.cc_tools
    assert world.hero("Pharah").flyer and not world.hero("Reinhardt").flyer
    assert world.hero("Reinhardt").barrier_hp >= 1000
    assert world.hero("Kiriko").cleanse_tools
    assert world.heal_bench > 0


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


def test_team_facts_appear_per_side_and_matchup_only_with_both(world):
    fs = engine.generate(world, "King's Row", ["Zarya", "Pharah"], [])
    scopes = {f.scope for f in fs.facts}
    assert "team" in scopes and "matchup" not in scopes
    assert fs.find("team.tanks", "red")
    fs = engine.generate(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"])
    assert fs.find("team.coverage", "blue") and fs.find("matchup.net_edges")
    assert any("Zarya is answered by blue Reinhardt" in f.text for f in fs.facts)


def test_board_context_facts_warn_and_cite(world):
    fs = engine.generate(world, None, ["Zarya"], ["Ana"])
    assert any(f.text.startswith("WARNING: blue Ana is answered by red Zarya")
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
    assert {"hero.rate_alt", "hero.perk_effect", "playbook.catalog"} <= keys, keys
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
    assert {"playbook.archetype", "playbook.catalog"} <= {f.key for f in side}
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
