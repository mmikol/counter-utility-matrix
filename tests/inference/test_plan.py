"""The board in prose: the momentum verdict read off the two current comps,
each half-drafted seat through its fill, and the game plan - the style, the
terrain and the stages it names, and nothing the board contradicts."""

import copy
import os

import pytest

from inference import catalog
from inference.expr import Expr
from tests.inference import FIXTURE_PLAYBOOK
from ui.facts import board_facts
from ui.facts.draft import Draft
from ui.facts.team import team_metrics


def test_the_momentum_verdict_reads_the_two_current_comps():
    from inference import plan
    from inference.result import Result
    fix = catalog.load(FIXTURE_PLAYBOOK)

    def comp(blue, score, best, partial=False):
        return Result(kind="current", map_name=None, red=[], blue=blue, locked=blue,
                      catalog=fix, score=score, best=best, partial=partial)
    even = plan.momentum(plan.Seats(comp(["a"], 8, 10), comp(["b"], 7.8, 10)))
    assert even["verdict"].startswith("even") and even["blue"] == 80 and even["red"] == 78
    blue = plan.momentum(plan.Seats(comp(["a"] * 6, 9, 10), comp(["b"] * 6, 5, 10),
                                    countered=comp(["a"] * 6, 3, 10)))
    assert blue["verdict"].startswith("blue ahead by 40") and blue["countered"] == 30
    assert "your picks hold 30 / 100" in blue["verdict"] and not blue["partial"]
    red = plan.momentum(plan.Seats(comp(["a"], 2, 10, partial=True), comp(["b"] * 6, 9, 10)))
    assert red["verdict"].startswith("red ahead by 70") and "(partial picks)" in red["verdict"]
    only_red = plan.momentum(plan.Seats(comp([], 0, 10), comp(["b"], 5, 10)))
    assert only_red["verdict"].startswith("red has revealed")


def test_both_seats_are_read_through_their_fills_while_half_drafted(
        synthetic_world, scratch_playbook):
    """Blue's share used to be its fill's and red's the sum over its picks
    alone, which reads low, so a half-drafted blue always led. Each seat is
    now read through its own fill and the countered case fills blue's picks
    too: a board where both seats hold the same one pick on an unsided map
    is the same board from either side, and reads even."""
    from inference import engine
    b = engine.board(synthetic_world, Draft("Ember Ruins", ("Anvil",), ("Anvil",)),
                     catalog=scratch_playbook)
    assert b.current.partial and b.red_current.partial
    assert b.momentum["blue"] == b.momentum["red"] == b.fill.to_dict()["normalized"]
    assert b.momentum["verdict"].startswith("even - blue %d, red %d (partial picks)"
                                            % (b.momentum["blue"], b.momentum["red"]))
    assert b.momentum["odds"] == {"blue": 50, "red": 50}
    assert b.countered.kind == "countered" and len(b.countered.blue) == 6
    assert "Anvil" in b.countered.locked and not b.countered.partial
    assert b.momentum["countered"] == b.countered.to_dict()["normalized"]


@pytest.mark.invariant
def test_the_plan_names_every_maps_derived_style(world, kings_row_board):
    """Every map's plan names the style its rates reward and cites no note: a
    map has none. One board is solved through the public path; the other maps'
    plans are composed from that board's optimal."""
    from inference import plan
    blue_r = kings_row_board.blue
    for m in world.maps.values():
        assert m.style_top and all(note is None for _, note in m.styles.values()), m.name
        said = (kings_row_board.plan if m.name == "King's Row"
                else plan.plan(world, m, "", [], [], blue_r))
        assert "The map rewards %s" % m.style_top in said, m.name
        assert "archetype" not in said and "authored" not in said, m.name
    assert plan._and(["A"]) == "A" and plan._and(["A", "B", "C"]) == "A, B and C"


@pytest.mark.invariant
def test_the_plan_names_the_terrain_the_facts_hold_and_no_other(world, kings_row_board):
    """The map sentence names the map.terrain facts above the ordinary map, largest
    first; a board whose facts hold none for the map names none."""
    from inference import plan
    from ui.facts import model
    blue_r = kings_row_board.blue
    above = [
        f.value["feature"] for f in blue_r.facts.find("map.terrain", "King's Row")
        if f.value["z"] > 0][:plan.TERRAIN_NAMED]
    assert above and above[0] == "chokes"
    assert set(plan.TERRAIN_GROUND) == set(model.TERRAIN_FEATURES)
    sentence = "The wiki's article stresses %s." % plan._and(
        plan.TERRAIN_GROUND[f] for f in above)
    assert sentence in kings_row_board.plan.split("\n")[0]
    # these facts are King's Row's: another map's plan reads none of them
    assert "stresses" not in plan.plan(world, world.map("Ilios"), "", [], [], blue_r)


@pytest.mark.invariant
def test_the_plan_names_the_stages_the_facts_hold_and_no_other(world, kings_row_board):
    """One sentence names the stages with a map.stage_terrain fact, in play order,
    STAGES_NAMED at most, each by the features its fact holds; no fact, no sentence."""
    import copy

    from inference import plan
    blue_r = kings_row_board.blue
    held = blue_r.facts.find("map.stage_terrain", "King's Row")
    assert [f.value["stage"] for f in held] == ["Assault", "Escort"]
    named = [
        plan._and(plan.TERRAIN_GROUND[x["feature"]] for x in f.value["features"])
        for f in held]
    sentence = "Assault has the %s; Escort the %s." % tuple(named)
    assert sentence in kings_row_board.plan.split("\n")[0]

    def first_line(name):
        r = copy.copy(blue_r)
        r.facts = board_facts.generate(world, Draft(name))
        return plan.plan(world, world.map(name), "", [], [], r).split("\n")[0]
    assert "Well has the environmental hazards." in first_line("Ilios")
    assert "Lighthouse" not in first_line("Ilios") and "Ruins" not in first_line("Ilios")
    # three stages at most: the largest, told in play order
    suravasa = world.map("Suravasa")
    r = copy.copy(blue_r)
    r.facts = board_facts.generate(world, Draft("Suravasa"))
    assert not r.facts.find("map.stage_terrain")
    for stage, z in zip(suravasa.stages[:4], (1.0, 4.0, 3.0, 2.0), strict=True):
        r.facts.add("map", "Suravasa", "map.stage_terrain", stage, source="stage_terrain",
                    value={"stage": stage, "features": [{"feature": "cover", "z": z}]})
    assert plan.STAGES_NAMED == 3 and "%s has the cover; %s the cover; %s the cover." % tuple(
        suravasa.stages[1:4]) in plan.plan(world, suravasa, "", [], [], r)
    assert suravasa.stages[0] not in plan.plan(world, suravasa, "", [], [], r)
    # no stage fact: Oasis has stages and no text of theirs, Dorado no stages
    for name in ("Oasis", "Dorado", "Colosseo"):
        assert not board_facts.generate(world, Draft(name)).find("map.stage_terrain")
        assert " has the " not in first_line(name), name
        assert not any(stage in first_line(name) for stage in world.map(name).stages), name


@pytest.mark.invariant
def test_the_plan_says_nothing_the_board_contradicts(world):
    """A mirror is told as one, a six solved before red reveals a pick names the
    likely six it counters, "Above all" leaves out the shape every six pays and
    a rule named for another style, and the family follows the style tags."""
    from types import SimpleNamespace as Ns

    from inference import plan
    from inference.result import Result
    from inference.scoring import Contribution
    m = copy.copy(world.map("King's Row"))
    m.styles = {"brawl": (1.0, None), "dive": (-0.5, None), "poke": (0.0, None)}   # a brawl map
    rules = [
        Ns(
            id="two-supports-hold", name="Two supports hold a six", kind="constraint",
            form="scored", category="shape", when=None, pending=False),
        Ns(
            id="dive-the-pocket", name="Dive the pocket", kind="constraint", form="scored",
            category="matchup", when=Expr("enemy.dmg_amp >= 2"), pending=False),
        Ns(
            id="brawl-maps", name="Brawl maps reward durability", kind="heuristic",
            form="heuristic", category="map", when=Expr("map.style_top == 'brawl'"),
            pending=False),
        Ns(
            id="poke-needs-reach", name="Poke needs reach", kind="heuristic",
            form="heuristic", category="shape", when=Expr("team.style_lean == 'poke'"),
            pending=False),
        Ns(
            id="unmet", name="An unmet need", kind="heuristic", form="heuristic",
            category="general", when=None, pending=False)]
    terms: list[Contribution] = [
        {
            "id": r.id, "kind": r.kind, "form": "scored" if r.kind == "constraint" else "heuristic",
            "applies": True, "weighted": 2.0, "metric": None}
        for r in rules[:4]]
    terms.append({"id": "unmet", "kind": "heuristic", "form": "heuristic", "applies": True,
                  "weighted": -0.5, "metric": None, "need": True})
    red_h = [world.hero("Reinhardt"), world.hero("Zarya")]
    theirs = team_metrics(world, red_h, m, [])
    red_lean = theirs["style_lean"] or theirs["style_top"]
    assert red_lean == "brawl"
    # a real Result, not a stand-in: _plan reads .facts, which Result defines
    six = Result(kind="infer", map_name=m.name, red=["Reinhardt", "Zarya"], blue=[],
                 locked=[], catalog=rules, playstyle="brawl", contributions=terms)
    said = plan.plan(world, m, "", [], red_h, six)                     # a mirror
    assert "(Reinhardt, Zarya) lean brawl too: %s." % plan.SAME_LEAN["brawl"] in said
    assert plan.THEIR_LEAN["brawl"] not in said
    assert "Above all: brawl maps reward durability." in said
    six.playstyle = "poke"
    said = plan.plan(world, m, "", [], red_h, six)
    assert "lean brawl: %s." % plan.THEIR_LEAN["brawl"] in said
    assert "but against this red the six leans poke" in said
    assert "Above all: brawl maps reward durability; poke needs reach." in said
    said = plan.plan(world, m, "", [], [], six)                        # red revealed nothing
    assert "this red" not in said and "but the six leans poke" in said
    assert "No red pick yet: the six counters their likely six (Reinhardt, Zarya)." in said
    tanks = plan._family(world, m, "brawl", "tank", ["Zarya"])
    tagged = [
        h for h in world.heroes.values()
        if h.role == "tank" and "brawl" in h.styles and h.released and h.name != "Zarya"]
    assert set(tanks) <= {h.name for h in tagged} and "Reinhardt" in tanks
    assert len(tanks) == min(plan.FAMILY_SIZE, len(tagged))
    assert "Zarya" not in tanks and "Sigma" not in tanks             # banned; not tagged brawl
    # fewest tags first, then the best win rate here
    keys = [(len(world.hero(n).styles), -(world.hero(n).map_win(m.id) or world.hero(n).win or 0.0))
            for n in tanks]
    assert keys == sorted(keys)
    alone = [h for h in tagged if h.styles == {"brawl"}]
    assert [world.hero(n) for n in tanks[:len(alone)]] == sorted(
        alone, key=lambda h: -(h.map_win(m.id) or h.win or 0.0))[:plan.FAMILY_SIZE]
    assert "Tanks: %s." % ", ".join(plan._family(world, m, "poke", "tank", [])) in said


def test_a_playbook_that_scores_nothing_gets_a_plan_that_claims_no_counter(
        synthetic_world, tmp_path):
    """With nothing scored the six is only the highest win rates the search
    found, so the plan says that: no counter to their likely six, nothing
    built to fit together, and the style worded from the roles the six
    actually holds - which a support-less six would not be told to lean on."""
    import shutil

    from inference import engine, plan
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, "open-queue-tanks.md"), tmp_path)
    limit_only = catalog.load(str(tmp_path))
    assert not catalog.has_scoring_terms(limit_only)
    for draft in (Draft(), Draft("Harbor Gate", side="attack")):
        b = engine.board(synthetic_world, draft, catalog=limit_only)
        assert "the six counters" not in b.plan, draft
        assert "built to fit together" not in b.plan, draft
        assert "the six is the highest win-rate six the search found" in b.plan, draft
        assert "No red pick yet: their likely six is " in b.plan, draft
        roles = [p["role"] for p in b.blue.picks]
        for role in ("tank", "damage", "support"):
            n = roles.count(role)
            assert ("%d %s" % (n, role) if n else "no %s" % role) in b.plan, (draft, role)
    lacking = {"tank": 2, "damage": 4, "support": 0}
    assert plan._shape(lacking) == "2 tanks, 4 damage and no support"
    assert "supports who can follow" not in plan._advice("dive", lacking)
    assert "no support can follow" in plan._advice("dive", lacking)
