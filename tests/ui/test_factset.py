"""The FactSet itself: how a fact is filed and found. Pure - no database,
so it runs on the pull-request gate with the rest of the arithmetic."""

import dataclasses

import pytest

from ui.facts.draft import Draft
from ui.facts.factset import FactSet


def test_a_fact_is_found_under_every_metric_its_sentence_states():
    """One sentence often carries several metrics. `also` indexes the fact
    under each, so a strategy that names any of them cites the line that says
    it - no table in a third module guessing which fact holds which number."""
    fs = FactSet(Draft())
    fid = fs.add("team", "blue", "team.tanks", "blue team shape: 2 tank / 2 dps / 2 support",
                 source="derived:team.tanks", also=("team.damage", "team.supports"))
    for key in ("team.tanks", "team.damage", "team.supports"):
        [found] = fs.find(key, "blue")
        assert found.id == fid and found.key == "team.tanks"   # the key it is worded around
    assert fs.find("team.damage", "red") == []                 # the subject still narrows
    assert fs.count == 1                                       # one fact, three ways in


def test_a_metric_alone_finds_every_fact_a_subject_finds():
    """find(key) is every fact that states the metric, whoever it is about;
    a subject narrows that list and never reaches past it."""
    fs = FactSet(Draft())
    blue = fs.add("team", "blue", "team.coverage", "blue team coverage: answers 2/2 red picks",
                  source="derived:team.coverage", also=("team.coverage_share",))
    red = fs.add("team", "red", "team.coverage", "red team coverage: answers 1/2 blue picks",
                 source="derived:team.coverage", also=("team.coverage_share",))
    assert [f.id for f in fs.find("team.coverage_share")] == [blue, red]    # id order
    assert [f.id for f in fs.find("team.coverage_share", "blue")] == [blue]
    for key in ("team.coverage", "team.coverage_share"):
        for subject in ("blue", "red"):
            assert {f.id for f in fs.find(key, subject)} <= {f.id for f in fs.find(key)}
    # an `also` that repeats the key files the fact once
    own = fs.add("team", "blue", "team.tanks", "blue team shape: 2 tank",
                 source="derived:team.tanks", also=("team.tanks", "team.damage"))
    assert [f.id for f in fs.find("team.tanks")] == [own]
    assert [f.id for f in fs.find("team.tanks", "blue")] == [own]


def test_a_fact_is_a_frozen_record_and_the_draft_serves_as_lists():
    """A fact, once numbered, does not change; the board it describes reaches
    the JSON as the lists the page and the MCP payload have always read."""
    fs = FactSet(Draft("King's Row", ("Zarya",), ("Ana",), ("Sombra",), "attack"))
    fs.add(
        "hero", "Ana", "hero.pool", "Ana pool: 250", source="heroes", value=250, unit="hp",
        team="blue")
    [fact] = fs.facts
    with pytest.raises(dataclasses.FrozenInstanceError):
        fact.text = "Ana pool: 300"
    served = fs.to_dict()
    assert (served["map"], served["red"], served["blue"], served["bans"], served["side"]) == \
        ("King's Row", ["Zarya"], ["Ana"], ["Sombra"], "attack")
    assert served["facts"] == [{"id": "F1", "scope": "hero", "subject": "Ana", "team": "blue",
                                "key": "hero.pool", "text": "Ana pool: 250", "value": 250,
                                "unit": "hp", "source": "heroes"}]
