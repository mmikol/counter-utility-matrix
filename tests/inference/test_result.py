"""A Result as it reads: unscored and why, the rendered breakdown, and the
facts a pick and a contribution cite."""

import os
import shutil

import pytest

from inference import catalog
from tests.inference import FIXTURE_PLAYBOOK
from ui.facts import board_facts
from ui.facts.draft import Draft


@pytest.mark.invariant
def test_a_playbook_that_scores_nothing_reads_unscored(world):
    """Hard limits and prose alone tie every legal six at zero: the results
    carry no share of a best, say so, and the verdict is the one line."""
    from inference import engine
    reference = catalog.load(FIXTURE_PLAYBOOK)
    assert catalog.has_scoring_terms(reference)
    limit_only = [h for h in reference if h.form == "limit" and not h.soft]
    assert limit_only and not catalog.has_scoring_terms(limit_only)
    b = engine.board(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana", "Reinhardt")),
                     catalog=limit_only)
    d = b.to_dict()
    for key in ("blue", "red"):                     # the optimal is the reference: 100, always
        assert d[key]["scoring"] is True and d[key]["normalized"] == 100
    for key in ("current", "red_current", "fill", "countered"):
        assert d[key]["scoring"] is False and d[key]["normalized"] is None
        assert all(a["normalized"] is None for a in d[key]["alternatives"])
    assert d["momentum"]["verdict"].startswith("unscored") and d["momentum"]["blue"] is None
    assert "(unscored)" in b.current.rendered() and "UNSCORED:" in b.current.rendered()
    scored = engine.board(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana", "Reinhardt")),
                          catalog=reference).to_dict()
    assert scored["current"]["scoring"] is True
    assert scored["current"]["normalized"] is None   # two picks of six: no share to give
    assert 0 < scored["fill"]["normalized"] <= 100   # the filled six carries it
    assert scored["current"]["unscored"] is None


@pytest.mark.invariant
def test_a_scoring_strategy_that_waits_on_its_board_reads_unscored_with_the_reason(world,
                                                                                    tmp_path):
    """A playbook whose only scoring term is guarded (hitscan cover while red
    fields a flier) scores nothing until the guard holds: the best six itself
    is zero, so no comp is a share of anything - the board says which
    strategy waits and for what, and scores once the flier appears."""
    from inference import engine
    # the two-tank limit and one guarded heuristic: a scoring term that waits on red
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, "open-queue-tanks.md"), tmp_path)
    (tmp_path / "fliers-need-cover.md").write_text(
        "---\nname: Fliers need hitscan cover\nkind: heuristic\ndirection: maximize\n"
        "metric: team.hitscan\nweight: 1\nwhen: matchup.flyers >= 1\n---\nx\n", "utf-8")
    scratch = catalog.load(str(tmp_path))
    assert catalog.has_scoring_terms(scratch)
    grounded = engine.board(world, Draft("King's Row", ("Zarya", "Ana"), ("Reinhardt", "Cassidy")),
                            catalog=scratch).to_dict()
    for key in ("blue", "red"):
        assert grounded[key]["scoring"] is True and grounded[key]["normalized"] == 100
    for key in ("current", "red_current", "fill"):
        assert grounded[key]["scoring"] is False and grounded[key]["normalized"] is None
        assert "Fliers need hitscan cover waits for matchup.flyers >= 1" in \
            grounded[key]["unscored"]
    # against red's optimal six the guard may hold (their best counter can field a flier):
    # then that one result scores, and says nothing about waiting
    countered = grounded["countered"]
    assert countered["scoring"] is (countered["unscored"] is None)
    assert grounded["momentum"]["verdict"].startswith("unscored on this board")
    assert "waits for matchup.flyers >= 1" in grounded["momentum"]["verdict"]
    # no picks at all: blue's seat counters red's likely six, the optimal is the
    # reference (100), and the verdict is the plain "no picks yet"
    empty = engine.board(world, Draft(), catalog=scratch).to_dict()
    assert empty["blue"]["normalized"] == 100 and empty["blue"]["unscored"] is None
    # matchup.flyers counts fliers tanks aside: a flying tank does not raise the guard
    if any(
            world.hero(name).flyer and world.hero(name).role != "tank"
            for name in empty["expected"]["blue"]):
        assert empty["momentum"]["verdict"] == "no picks yet on either side"
    else:                         # the likely six fields no such flier: the one rule waits here too
        assert "waits for matchup.flyers >= 1" in empty["momentum"]["verdict"]
    assert empty["blue"]["red"] == empty["expected"]["blue"]           # countering the likely six
    flying = engine.board(world, Draft("King's Row", ("Zarya", "Pharah"), ("Reinhardt", "Cassidy")),
                          catalog=scratch).to_dict()
    assert flying["blue"]["scoring"] is True and flying["blue"]["normalized"] == 100
    assert flying["current"]["unscored"] is None
    assert flying["current"]["normalized"] is None   # partial: the fill holds the share
    # blue fields no flier, so red's seat still waits: the verdict reads each side on its own
    assert flying["red_current"]["scoring"] is False
    verdict = flying["momentum"]["verdict"]
    assert verdict.startswith("blue %d / 100" % flying["fill"]["normalized"])
    assert "red unscored: Fliers need hitscan cover waits for matchup.flyers >= 1" in verdict
    assert flying["momentum"]["blue"] == flying["fill"]["normalized"]
    assert flying["momentum"]["red"] is None and flying["momentum"]["odds"] is None


def test_the_rendered_breakdown_marks_a_need():
    """A need reads at or below zero by design, so the breakdown says which
    terms are needs; the flag rides to_dict() on each contribution."""
    from inference.result import Result
    r = Result(
        kind="evaluate", map_name=None, red=[], blue=[], locked=[], catalog=[],
        contributions=[
            {
                "id": "a-reward", "kind": "heuristic", "form": "heuristic",
                "applies": True, "weighted": 0.25, "metric": None, "need": False},
            {
                "id": "a-need", "kind": "heuristic", "form": "heuristic",
                "applies": True, "weighted": -0.11, "metric": None, "need": True}])
    assert "breakdown: a-reward +0.25 · a-need -0.11 (need)" in r.rendered()
    assert [c["need"] for c in r.to_dict()["contributions"]] == [False, True]


@pytest.mark.invariant
def test_a_metric_printed_inside_another_fact_cites_that_fact(world):
    """team.range_max rides the range_median line and team.cleanse the invuln
    line; a rule on either cites that fact, not its guard's."""
    from inference.result import _cited_fact
    six = ["Reinhardt", "Sigma", "Ashe", "Cassidy", "Ana", "Kiriko"]
    fs = board_facts.generate(world, Draft("King's Row", ("Zarya",), tuple(six), side="attack"))
    for metric, line in (("team.range_max", "team.range_median"), ("team.melee", "team.hitscan"),
                         ("team.cleanse", "team.invuln"), ("team.dps_count", "team.dps_floor"),
                         ("matchup.exposure_share", "matchup.coverage_share")):
        fact = _cited_fact(fs, [metric, "team.style_top"])
        assert fact is not None and fact.key == line, metric


@pytest.mark.invariant
def test_a_mirror_pick_cites_its_own_facts_not_the_enemy_copy(world):
    """Tracer on both teams: our Tracer's reasons come from our side of the
    board - never "answers Ana" (our Ana, whom red's Tracer answers) and
    never "partner of Winston" (red's Winston)."""
    from inference import engine
    r = engine.evaluate(world, Draft("King's Row", ("Winston", "Genji", "Tracer"),
                                     ("D.Va", "Reinhardt", "Tracer", "Brigitte", "Lúcio", "Ana")))
    ours = next(p for p in r.picks if p["hero"] == "Tracer")
    partners = ours["why"].split(";")[0]          # red's Winston may answer her; he is no partner
    assert "answers Ana" not in ours["why"] and "Winston" not in partners
    clues = ("answers Genji", "answers Tracer", "partner of D.Va")
    assert any(clue in ours["why"] for clue in clues)
