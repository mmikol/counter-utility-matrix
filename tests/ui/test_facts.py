"""The UI layer: facts for a board, from the built database."""

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


def test_facts_are_densely_numbered_and_keyed(world):
    fs = engine.generate(world, "King's Row", ["Zarya", "Pharah"], ["Ana"])
    facts = [f for f in fs.facts if f.scope != engine.PLAYBOOK_SCOPE]
    assert [f.id for f in facts] == ["F%d" % i for i in range(1, len(facts) + 1)]
    assert all(f.key and f.scope and f.text for f in fs.facts)
    assert fs.facts[0].scope == "meta"
    assert {"map", "hero", "team", "matchup", "playbook"} <= {f.scope for f in fs.facts}


def test_every_named_hero_gets_a_hundred_independent_facts(world):
    fs = engine.generate(world, "King's Row", ["Tracer"], ["Ana"])
    for hero in ("Tracer", "Ana"):
        assert sum(1 for f in fs.facts if f.subject == hero) >= 100, hero
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
    src = open(model_module.__file__, encoding="utf-8").read()
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


@pytest.mark.invariant
def test_facts_are_the_authoritative_data_and_the_playbook_record_is_numbered_apart(world):
    # FACTS = HEROES ∪ MAPS ∪ META (F1..); the playbook's record rides below as S1..
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
    assert text.index("[S1]") > text.index(engine.PLAYBOOK_DIVIDER) > text.index("[F%d]" % len(facts))
    assert "STRATEGIES = CONSTRAINTS ∪ HEURISTICS" in [f.text for f in side if f.key == "playbook.catalog"][0]
