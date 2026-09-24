"""A board's facts from facts/board_facts.py, on the synthetic World: the
order and the numbering, the team and matchup facts, the warnings, the bans
and the sides, each worded from what tests/synthetic.py sets. No database."""

import pytest

from db import Refusal
from facts import board_facts, factset
from facts.draft import Draft


def test_every_fact_is_keyed_and_the_meta_comes_first(synthetic_world):
    fs = board_facts.generate(synthetic_world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",)))
    assert all(f.key and f.scope and f.text for f in fs.facts)
    assert fs.facts[0].scope == "meta" and fs.facts[0].text == (
        "blizzard rates: captured 2026-09-01, September 1, 2026 Patch (2026-09-01),"
        " Season 1 - role queue, pc, Americas")
    assert {"map", "hero", "team", "matchup", "playbook"} <= {f.scope for f in fs.facts}


def test_facts_are_the_authoritative_data_and_the_playbook_record_is_numbered_apart(
        synthetic_world):
    # FACTS = INDEPENDENT ∪ DEPENDENT (F1..); the playbook's record rides below as S1..
    fs = board_facts.generate(synthetic_world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",)))
    facts = [f for f in fs.facts if f.scope != factset.PLAYBOOK_SCOPE]
    side = fs.playbook
    assert facts and side
    assert all(f.id.startswith("F") for f in facts) and all(f.id.startswith("S") for f in side)
    assert [f.id for f in facts] == ["F%d" % i for i in range(1, len(facts) + 1)]
    assert [f.id for f in side] == ["S%d" % i for i in range(1, len(side) + 1)]
    assert {f.scope for f in facts} <= {"meta", "bans", "map", "hero", "team", "matchup"}
    assert [f.key for f in side] == ["playbook.catalog"]
    assert fs.count == len(facts) and fs.to_dict()["playbook_count"] == len(side)
    text = fs.rendered()
    assert text.startswith("[F1]") and factset.PLAYBOOK_DIVIDER in text
    divider = text.index(factset.PLAYBOOK_DIVIDER)
    assert text.index("[S1]") > divider > text.index("[F%d]" % len(facts))
    assert side[0].text == (
        "the playbook holds 2 constraints, 3 heuristics and 2 assumptions"
        " (STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS)")


def test_team_facts_appear_per_side_and_matchup_only_with_both(synthetic_world):
    w = synthetic_world
    fs = board_facts.generate(w, Draft("Harbor Gate", ("Mortar", "Gale")))
    scopes = {f.scope for f in fs.facts}
    assert "team" in scopes and "matchup" not in scopes
    assert fs.find("team.tanks", "red")
    fs = board_facts.generate(w, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm", "Anvil")))
    assert fs.find("team.coverage", "blue") and fs.find("matchup.net_edges")
    # the crowd-control line names every blue pick that carries a tool, read off the picks
    (cc,) = fs.find("team.cc_count", "blue")
    assert cc.text == "blue team crowd control: 1 pick; Anvil: Quake Slam"
    # the builder's counter: Mortar is answered by Anvil
    fs = board_facts.generate(w, Draft("Harbor Gate", ("Mortar",), ("Anvil",)))
    assert [f.text for f in fs.find("team.answer", "blue")] == [
        "red Mortar is answered by blue Anvil"]


def test_board_context_facts_warn_and_cite(synthetic_world):
    w = synthetic_world
    fs = board_facts.generate(w, Draft(None, ("Anvil",), ("Mortar",)))
    assert [f.text for f in fs.find("hero.vs_answered_by", "Mortar")] == [
        "WARNING: blue Mortar is answered by red Anvil"]
    fs = board_facts.generate(w, Draft("Harbor Gate", (), ("Balm", "Anvil")))
    assert [f.text for f in fs.find("hero.with_ally", "Balm")] == [
        "blue Balm + Anvil (2/3): the charm keeps the hammer swinging"]
    assert [f.text for f in fs.find("hero.map_win", "Balm")] == [
        "Balm on Harbor Gate (this map): wins 52.0%, picked 10.0%, banned 10.0%"]


def test_bans_become_facts_and_a_banned_pick_is_refused(synthetic_world):
    w = synthetic_world
    fs = board_facts.generate(w, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",),
                                       bans=("Needle", "Rook")))
    assert fs.draft.bans == ("Needle", "Rook")
    assert fs.find("bans.count")[0].text == "bans this match: 2 of 5 - Needle, Rook"
    assert len(fs.find("bans.hero")) == 2
    # Needle answers Gale and Rook answers Balm: each ban took an answer off the table
    assert fs.find("bans.answered_red")[0].text == (
        "banned Needle answered red Gale - that answer is off the table")
    assert fs.find("bans.answered_blue")[0].text == (
        "banned Rook answered blue Balm - that threat is gone")
    with pytest.raises(Refusal, match="banned this match"):
        board_facts.generate(w, Draft(None, ("Mortar",), ("Balm",), bans=("Balm",)))
    with pytest.raises(Refusal, match="unknown heroes"):
        board_facts.generate(w, Draft(bans=("Nemo",)))


def test_sides_exist_only_on_escort_and_hybrid(synthetic_world):
    w = synthetic_world
    fs = board_facts.generate(w, Draft("Harbor Gate", ("Mortar",), ("Balm",), side="attack"))
    assert fs.draft.side == "attack"
    assert [f.text for f in fs.find("map.side")] == ["blue attacks Harbor Gate; red defends"]
    assert fs.find("map.side_caveat")
    fs = board_facts.generate(w, Draft("Ember Ruins", side="attack"))
    assert fs.draft.side == ""
    assert [f.text for f in fs.find("map.side")] == [
        "Ember Ruins (Control) has no attacking or defending side"]
    with pytest.raises(Refusal, match="side must be"):
        board_facts.generate(w, Draft("Harbor Gate", side="left"))
