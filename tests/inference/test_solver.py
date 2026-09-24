"""The search on a board: shape limits, a need and its budget, partners that
only pay together, the scale a ban leaves alone, the ranking order and its
tie-breaks, a rule scaled by the metric it names, and the reference sample
of a small roster."""

import copy
import os
import shutil

import pytest

from db import Refusal
from inference import catalog
from tests.inference import FIXTURE_PLAYBOOK
from ui.facts.draft import Draft
from ui.facts.records import StyleScore, Synergy
from ui.facts.team import team_metrics


@pytest.mark.invariant
def test_shape_limits_bound_the_search_and_a_stricter_one_narrows_it(world, tmp_path):
    from inference import engine
    fix = catalog.load(FIXTURE_PLAYBOOK)
    # two tanks is allowed under the two-tank limit; a third is not, and is the queue's
    r = engine.infer(world, Draft("King's Row", ("Zarya",), ("Winston", "D.Va")), pool_size=4,
                     catalog=fix)
    assert {"Winston", "D.Va"} <= set(r.blue)
    with pytest.raises(Refusal, match="the queue allows at most 2 tanks"):
        engine.infer(world, Draft("King's Row", (), ("Winston", "D.Va", "Reinhardt")),
                     pool_size=4, catalog=fix)
    # a stricter authored limit narrows the search the same way
    for name in os.listdir(FIXTURE_PLAYBOOK):
        if name != "open-queue-tanks.md":
            shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    (tmp_path / "shape.md").write_text(
        "---\nname: role queue\nkind: constraint\nrequire: team.tanks == 2 and"
        " team.damage == 2 and team.supports == 2\n---\nx\n", "utf-8")
    cat = catalog.load(str(tmp_path))
    r = engine.infer(world, Draft("King's Row", ("Zarya",), ("Ana",)), pool_size=4, catalog=cat)
    roles = sorted(world.hero(n).role for n in r.blue)
    assert roles == ["damage", "damage", "support", "support", "tank", "tank"]


@pytest.mark.invariant
def test_a_rule_guarded_on_the_six_itself_is_a_need_and_a_state_has_a_budget(world, tmp_path):
    """"A solo healer needs an escape" must not pay a six for fielding one
    support: met in full it costs nothing, unmet it costs the weight, and the
    needs written on one guard cost NEED_BUDGET together at most. A guard on
    the board (red, the map) stays a reward."""
    from inference import engine, scoring
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, "open-queue-tanks.md"), tmp_path)
    rule = ("---\nname: %s\nkind: heuristic\ndirection: maximize\nmetric: %s\nweight: 2\n"
            "when: %s\n---\nx\n")
    for i, metric in enumerate(("team.mobility_count", "team.cc_count", "team.armor_total")):
        (tmp_path / ("solo-%d.md" % i)).write_text(
            rule % ("Solo %d" % i, metric, "team.supports <= 1"), "utf-8")
    (tmp_path / "their-fliers.md").write_text(
        rule % ("Their fliers", "team.hitscan", "matchup.flyers >= 1"), "utf-8")
    scratch = catalog.load(str(tmp_path))
    solo = engine.evaluate(world, Draft("King's Row", ("Pharah",),
                                        ("Reinhardt", "Cassidy", "Tracer", "Genji", "Mei", "Ana")),
                           catalog=scratch).to_dict()
    terms = {c["id"]: c for c in solo["contributions"]}
    needs = [terms["solo-%d" % i] for i in range(3)]
    assert all(c["applies"] and c["need"] and c["weighted"] <= 0 for c in needs)
    assert sum(c["weighted"] for c in needs) >= -scoring.NEED_BUDGET - 1e-9
    assert terms["their-fliers"]["need"] is False and terms["their-fliers"]["weighted"] >= 0
    paired = ("Reinhardt", "Cassidy", "Tracer", "Genji", "Kiriko", "Ana")
    pair = engine.evaluate(world, Draft("King's Row", ("Pharah",), paired),
                           catalog=scratch).to_dict()
    assert all(
        not c["applies"] and c["weighted"] == 0
        for c in pair["contributions"] if c["id"].startswith("solo-"))


@pytest.mark.invariant
def test_partners_that_only_pay_together_are_brought_in_together(world, tmp_path):
    """One slot at a time, a pair worth nothing apart is never met: each partner
    alone only costs. The playbook here pays one synergy pair, the two
    lowest-standing heroes of their roles, outside the pools. The best six holds
    both, with the locked pick, the ban and the shape kept; the pair step off,
    the search stops short of it."""
    from inference import solver as solver_module
    (tmp_path / "shape.md").write_text(
        "---\nname: role queue\nkind: constraint\nrequire: team.tanks == 2 and"
        " team.damage == 2 and team.supports == 2\n---\nx\n", "utf-8")
    rule = "---\nname: %s\nkind: heuristic\ndirection: maximize\nmetric: %s\nweight: %s\n---\nx\n"
    (tmp_path / "winning.md").write_text(rule % ("Winning", "team.win_mean", 1), "utf-8")
    (tmp_path / "together.md").write_text(rule % ("Together", "team.synergy_edges", 0.75), "utf-8")
    scratch = catalog.load(str(tmp_path))
    locked, banned = [world.hero("Reinhardt")], [world.hero("Mercy")]

    def solver_on(w):
        return solver_module.Solver(w, None, red=[], locked=locked, banned=banned,
                                    catalog=scratch, pool_size=3)

    alone = copy.copy(world)                   # the same roster, no synergy pair yet
    alone.synergies, alone.partners = {}, {}
    before = solver_on(alone)
    before.solve(top=1)
    last = {r: sorted((h for h in world.heroes.values() if h.role == r and h.released
                       and h not in locked and h not in banned), key=before._pool_key)[::-1]
            for r in ("tank", "damage", "support")}
    for a, b in ((last["support"][0], last["support"][1]), (last["tank"][0], last["damage"][0])):
        paired = copy.copy(world)
        pair = Synergy(1, "scratch")
        paired.synergies = {frozenset((a.id, b.id)): pair}
        paired.partners = {a.id: {b.id: pair}, b.id: {a.id: pair}}
        solver = solver_on(paired)
        top = solver.solve(top=1).ranked[0]
        pooled = {h.id for pool in solver.pools().values() for h in pool}
        assert a.id not in pooled and b.id not in pooled      # the sweep never saw either
        assert {a.name, b.name, "Reinhardt"} <= set(top.names) and "Mercy" not in top.names
        assert sorted(h.role for h in top.heroes) == ["damage"] * 2 + ["support"] * 2 + ["tank"] * 2
        assert any(c["id"] == "together" and c["raw"] == 1 for c in top.contributions)
        # with the pair step off, the two-at-once swap still reaches them: that is
        # what it is for. Only with both off is a pair outside the pool unreachable,
        # because a one-slot climb meets each partner alone and neither pays alone.
        single = solver_on(paired)
        single._pairs = list                   # the pair step off
        pair_off = single.solve(top=1).ranked[0]
        assert {a.name, b.name} <= set(pair_off.names)

        # a pair outside the pool is unreachable only when all three are off: the
        # restarts can land on both partners at once, as can the two-at-once swap.
        neither = solver_on(paired)
        neither._pairs = list                  # the pair step off
        neither._two_swap = lambda leader, roster, known: leader
        neither._restarts = lambda leader, roster, known, n=0: leader
        short = neither.solve(top=1).ranked[0]
        assert not {a.name, b.name} & set(short.names) and short.score < top.score


@pytest.mark.invariant
def test_a_ban_does_not_rescale_the_board(world):
    """The reference sample fixes every heuristic's [lo, hi], so it must not
    depend on the bans: banning a hero on neither team would otherwise move the
    score of an unchanged six, and `the best six here` would stop being a
    function of the six. Bans screen the candidate field, not the scale."""
    from inference import catalog as catalog_module
    from inference import scoring
    from inference import solver as solver_module
    catalog = catalog_module.load()
    red = ["Zarya", "Pharah"]
    six = ["Reinhardt", "D.Va", "Ashe", "Sojourn", "Ana", "Kiriko"]
    absent = [
        h.name for h in world.heroes.values()
        if h.released and h.name not in six and h.name not in red][:2]

    def score_under(bans):
        m, red_h, _, bans_h = world.resolve("King's Row", red, [], bans)
        solver = solver_module.Solver(world, m, red=red_h, locked=[], banned=bans_h,
                                      side="attack", catalog=catalog)
        solver.freeze_bounds()
        cand = solver.prepare(scoring.Candidate([world.hero(n) for n in six]))
        return solver.score(cand, detail=False).score

    # the same six, the same number of bans, a different hero banned
    first = score_under([absent[0], "Sombra"])
    second = score_under([absent[1], "Sombra"])
    assert abs(first - second) < 1e-9, (first, second)


@pytest.mark.invariant
def test_the_order_of_a_six_does_not_decide_the_ranking(world):
    """_rank_key's third element breaks ties, so it has to be a property of the
    hero set - in seat order one set keys 720 ways."""
    from inference import scoring
    from inference import solver as solver_module
    heroes = [world.hero(n) for n in ("Reinhardt", "D.Va", "Ashe", "Sojourn", "Ana", "Kiriko")]
    one = scoring.Candidate(heroes)
    other = scoring.Candidate(list(reversed(heroes)))
    one.score = other.score = 1.0
    one.tiebreak = other.tiebreak = 0.5
    assert solver_module.Solver._rank_key(one) == solver_module.Solver._rank_key(other)


@pytest.mark.invariant
def test_a_rule_scales_by_the_metric_it_names(world, tmp_path):
    """`confidence:` is an engine field, not a rule: a heuristic names any numeric
    metric and its weight rides on that metric's place between the low and high of
    whatever population the metric actually varies over. Nothing in the code knows
    which metric any rule names. The rule is written here, beside the reference
    playbook, so the test holds whatever the shipped playbook carries."""
    from inference import engine, scoring
    from inference import solver as solver_module
    shutil.copytree(FIXTURE_PLAYBOOK, tmp_path, dirs_exist_ok=True)
    (tmp_path / "fit-the-map-style.md").write_text(
        "---\nname: Pick into what the map rewards\nkind: heuristic\ncategory: map\n"
        "metric: team.style_fit\ndirection: maximize\nweight: 2.5\nwhen: map.known == 1\n"
        "confidence: map.style_margin\n---\n# Pick into what the map rewards\n\n"
        "The share of the six tagged with the style the map rewards, weighed by how "
        "hard the map leans.\n", encoding="utf-8")
    playbook = catalog.load(str(tmp_path))
    scaled = [s for s in playbook if getattr(s, "confidence", None)]
    assert [s.id for s in scaled] == ["fit-the-map-style"]

    def points(map_name, strategy_id):
        m, red, _, _ = world.resolve(map_name, ["Zarya", "Pharah"], [], [])
        solver = solver_module.Solver(world, m, red=red, locked=[],
                                      side=engine._side(m, "attack"), catalog=playbook)
        solver.freeze_bounds()
        best = engine.infer(world, Draft(map_name, ("Zarya", "Pharah"),
                                         side=engine._side(m, "attack")),
                            top=1, catalog=playbook)
        cand = solver.prepare(scoring.Candidate([world.hero(n) for n in best.blue]))
        solver.score(cand, detail=True)
        return next(c for c in cand.contributions if c["id"] == strategy_id)

    # the map that leans hardest pays the map-style rule; the one that barely leans
    # pays almost none of it, and neither number is written anywhere
    sure = points("Nepal", "fit-the-map-style")
    unsure = points("Paraíso", "fit-the-map-style")
    assert sure["confidence_raw"] > unsure["confidence_raw"]
    assert sure["weighted"] > unsure["weighted"] * 5


@pytest.mark.invariant
def test_style_ties_break_by_name_so_hash_order_cannot_reach_the_answer(world):
    """A set of style names iterates in an order that changes with the process's
    hash seed; the tie-breaks must not depend on it - two views of the same
    heroes whose style sets iterate in opposite orders agree on every metric,
    and the same board solves to the same six twice in a row."""
    from inference import engine
    heroes = [world.hero(n) for n in ("Reinhardt", "Zarya", "Widowmaker", "Ana", "Lúcio", "Mercy")]
    forward = team_metrics(world, heroes, world.map("Ilios"), [])

    from ui.facts import model

    class Reversed(model.Hero):                # the same hero, its styles iterated backwards
        def __init__(self, hero):
            self.__dict__ = dict(hero.__dict__)
            self.styles = sorted(hero.styles, reverse=True)   # the other iteration order
    backward = team_metrics(world, [Reversed(h) for h in heroes], world.map("Ilios"), [])
    for key in ("style_top", "style_lean", "style_counts", "style_fit"):
        assert forward[key] == backward[key], key
    ilios = world.map("Ilios")
    derived = dict(ilios.styles)
    ilios.styles = {"poke": StyleScore(1.0, None), "dive": StyleScore(0.2, None),
                    "brawl": StyleScore(1.0, None)}
    try:
        assert ilios.style_top == "brawl" and ilios.style_margin == 0
    finally:
        ilios.styles = derived
    once = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",)))
    twice = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",)))
    assert once.blue == twice.blue and abs(once.score - twice.score) < 1e-12


@pytest.mark.invariant
def test_a_board_confidence_reads_the_boards_own_ban_count(world, tmp_path):
    """A confidence metric of the board is read over every map, and every map
    reads it with this board's bans: map.bans is the count made in this match,
    whatever map the population is drawn from."""
    from inference import scoring
    from inference import solver as solver_module
    shutil.copytree(FIXTURE_PLAYBOOK, tmp_path, dirs_exist_ok=True)
    (tmp_path / "scale-by-the-bans.md").write_text(
        "---\nname: Pick into what the map rewards once the bans are in\nkind: heuristic\n"
        "category: map\nmetric: team.style_fit\ndirection: maximize\nweight: 2.5\n"
        "when: map.known == 1\nconfidence: map.bans\n---\n"
        "# Pick into what the map rewards once the bans are in\n\n"
        "The share of the six tagged with the style the map rewards, weighed by how "
        "many bans are made.\n", encoding="utf-8")
    playbook = catalog.load(str(tmp_path))
    m, red, _, banned = world.resolve("King's Row", ["Zarya", "Pharah"], [],
                                      ["Widowmaker", "Sombra"])
    solver = solver_module.Solver(world, m, red=red, locked=[], banned=banned, side="attack",
                                  catalog=playbook)
    solver.freeze_bounds()
    assert solver.bounds["scale-by-the-bans" + scoring.CONFIDENCE_KEY] == (2.0, 2.0)


def test_a_roster_with_fewer_legal_sixes_than_the_reference_is_sampled_whole(synthetic_world):
    """Twelve heroes, four a role, hold fewer distinct sixes than REFERENCE_SIZE
    asks for. The reference is then every legal six once, in the seeded order,
    where the draw used to spin forever looking for more."""
    import itertools

    from inference import scale, scoring
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    shapes = set(scoring.legal_shapes(playbook))

    def shape(six):
        return tuple(sum(1 for h in six if h.role == r) for r in ("tank", "damage", "support"))
    released = [h for h in synthetic_world.heroes.values() if h.released]
    legal = {
        frozenset(h.id for h in six)
        for six in itertools.combinations(released, 6) if shape(six) in shapes}
    objective = scoring.Objective(synthetic_world, None, red=[], catalog=playbook)
    drawn = scale.sample(objective)
    assert len(legal) < scale.REFERENCE_SIZE
    assert [c.key for c in drawn] == [c.key for c in scale.sample(objective)]
    assert sorted(sorted(c.key) for c in drawn) == sorted(sorted(six) for six in legal)
