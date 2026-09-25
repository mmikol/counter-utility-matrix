"""The search on a board: the enumerated maximum it must reach, shape
limits, a soft limit that charges and never prunes, a need and its budget,
partners that only pay together, the scale a ban leaves alone, the ranking
order and its tie-breaks, a rule scaled by the metric it names and the
bounds its slices merge into, and the reference sample of a small roster.
Every board is the synthetic World's: no database."""

import copy
import dataclasses
import itertools
import os
import shutil

import pytest

from db import Refusal
from db.data.names import name_key
from facts.draft import Draft
from facts.records import StyleScore, Synergy
from facts.team import team_metrics
from inference import catalog
from inference.base import DEFAULT, OFF
from inference.shapes import legal_shapes
from tests.inference import FIXTURE_PLAYBOOK

# the reference playbook's shape limit tightened to Role Queue's two-two-two
ROLE_QUEUE = (
    "---\nname: role queue\nkind: constraint\nrequire: team.tanks == 2 and team.damage == 2"
    " and team.supports == 2\n---\nx\n")


def shape(six):
    """A six's (tanks, damage, supports)."""
    return tuple(sum(1 for h in six if h.role == r) for r in ("tank", "damage", "support"))


def legal_sixes(world, playbook, locked=(), banned=()):
    """Every six of the world's released heroes that holds the locked picks,
    fields no banned hero and takes a shape the playbook allows."""
    shapes = set(legal_shapes(playbook))
    taken = {h.id for h in (*locked, *banned)}
    free = [h for h in world.heroes.values() if h.released and h.id not in taken]
    sixes = ([*locked, *rest] for rest in itertools.combinations(free, 6 - len(locked)))
    return [six for six in sixes if shape(six) in shapes]


@pytest.mark.parametrize(("base", "pair"), [(OFF, ("Anvil", "Tansy")),
                                            (DEFAULT, ("Anvil", "Balm"))],
                         ids=["base-off", "base-on"])
def test_the_search_reaches_the_enumerated_maximum(synthetic_world, catalog_copy, base, pair):
    """The regression gate on the search. On six small boards - no red, red
    revealed, one lock, two locks, two bans, and a pair that pays only
    together - every legal six is enumerated and scored, and infer returns
    the best of them, tie-break included. Each role's pool holds two of its
    four heroes, so the reach-back steps have to find the rest. The playbook
    is the reference plus a role queue: a shape the pools cannot seat is
    never searched, and pools of two cannot seat three of a role. It holds
    with the default engine under the playbook and without it; the pair is
    two heroes the pools cut, and what ranks the pools differs between the
    two, so each names its own. A board this misses is a solver defect: fix
    the search, never swap the board out."""
    from inference import engine, scoring
    from inference import solver as solver_module
    with open(os.path.join(catalog_copy, "role-queue.md"), "w", encoding="utf-8") as handle:
        handle.write(ROLE_QUEUE)
    fix = catalog.load(catalog_copy)
    assert catalog.has_scoring_terms(fix)

    def searched(world, draft):
        m, red, locked, banned = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
        solver = solver_module.Solver(world, m, red=red, locked=locked, banned=banned,
                                      side=draft.side, catalog=fix, base=base, pool_size=2)
        solver.freeze_bounds()
        return solver, legal_sixes(world, fix, locked, banned)

    # the pair: two heroes the pools cut on a world with no synergies, made the
    # one synergy pair of a copy of the world
    pair_board = Draft("Salt Flats", ("Anvil",))
    alone = copy.copy(synthetic_world)
    alone.synergies, alone.partners = {}, {}
    solver, _ = searched(alone, pair_board)
    a, b = (synthetic_world.hero(name) for name in pair)
    assert not {a.id, b.id} & {h.id for pool in solver.pools().values() for h in pool}
    paired = copy.copy(synthetic_world)
    synergy = Synergy(1, "scratch")
    paired.synergies = {frozenset((a.id, b.id)): synergy}
    paired.partners = {a.id: {b.id: synergy}, b.id: {a.id: synergy}}
    boards = [
        (synthetic_world, Draft("Harbor Gate", side="attack")),
        (synthetic_world, Draft("Ember Ruins", ("Mortar", "Gale"))),
        (synthetic_world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",), side="defense")),
        (synthetic_world, Draft("Salt Flats", ("Anvil",), ("Kite", "Needle"))),
        (synthetic_world, Draft("Ember Ruins", ("Rook",), (), ("Myrrh", "Flint"))),
        (paired, pair_board)]
    missed, reached_back = [], []
    for world, draft in boards:
        solver, sixes = searched(world, draft)
        scored = [solver.score(solver.prepare(scoring.Candidate(six)), detail=False)
                  for six in sixes]
        feasible = sorted((c for c in scored if not c.violations), key=solver._rank_key)
        best = feasible[0]
        assert best.score > feasible[-1].score, draft          # the playbook tells sixes apart
        got = engine.infer(world, draft, catalog=fix, pool_size=2, top=1, base=base)
        if sorted(got.blue) != sorted(best.names) or abs(got.score - best.score) > 1e-9:
            missed.append("%s: %.6f %s, enumerated %.6f %s"
                          % (draft, got.score, sorted(got.blue), best.score, sorted(best.names)))
        seated = {h.id for pool in solver.pools().values() for h in pool}
        seated |= {h.id for h in solver.locked}
        reached_back += [h.name for h in best.heroes if h.id not in seated]
        if world is paired:
            assert {a.name, b.name} <= set(best.names)     # the pair pays, and is fielded
    assert not missed, "the search misses the enumerated maximum:\n  " + "\n  ".join(missed)
    assert reached_back                    # some board's best six holds a hero the pools cut


def test_shape_limits_bound_the_search_and_a_stricter_one_narrows_it(synthetic_world, tmp_path):
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)
    # two tanks is allowed under the two-tank limit; a third is not, and is the queue's
    r = engine.infer(world, Draft("Harbor Gate", ("Needle",), ("Anvil", "Kite")), pool_size=4,
                     catalog=fix)
    assert {"Anvil", "Kite"} <= set(r.blue)
    with pytest.raises(Refusal, match="the queue allows at most 2 tanks"):
        engine.infer(world, Draft("Harbor Gate", (), ("Anvil", "Kite", "Mortar")),
                     pool_size=4, catalog=fix)
    # a stricter authored limit narrows the search the same way
    for name in os.listdir(FIXTURE_PLAYBOOK):
        if name != "open-queue-tanks.md":
            shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    (tmp_path / "shape.md").write_text(ROLE_QUEUE, "utf-8")
    cat = catalog.load(str(tmp_path))
    r = engine.infer(world, Draft("Harbor Gate", ("Needle",), ("Balm",)), pool_size=4,
                     catalog=cat)
    roles = sorted(world.hero(n).role for n in r.blue)
    assert roles == ["damage", "damage", "support", "support", "tank", "tank"]


def test_a_soft_limit_charges_its_penalty_and_never_prunes(synthetic_world):
    """The reference playbook's anti-air is soft: against red's flier, a six
    with no hitscan breaks it, stays a candidate and pays its 2.5."""
    from inference import scoring
    w = synthetic_world
    objective = scoring.Objective(w, w.map("Harbor Gate"), red=[w.hero("Gale")],
                                  catalog=catalog.load(FIXTURE_PLAYBOOK), base=DEFAULT)
    cand = scoring.Candidate(
        [w.hero(n) for n in ("Anvil", "Mortar", "Balm", "Myrrh", "Sorrel", "Tansy")])
    objective.score(objective.prepare(cand))
    assert cand.violations == []
    [term] = [c for c in cand.contributions if c["id"] == "anti-air"]
    assert term["applies"] and term["ok"] is False and term["weighted"] == -2.5


def test_a_rule_guarded_on_the_six_itself_is_a_need_and_a_state_has_a_budget(
        synthetic_world, tmp_path):
    """"A solo healer needs an escape" must not pay a six for fielding one
    support: met in full it costs nothing, unmet it costs the weight, and the
    needs written on one guard cost NEED_BUDGET together at most. A guard on
    the board (red, the map) stays a reward."""
    from inference import engine, scoring
    world = synthetic_world
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, "open-queue-tanks.md"), tmp_path)
    rule = ("---\nname: %s\nkind: heuristic\ndirection: maximize\nmetric: %s\nweight: 2\n"
            "when: %s\n---\nx\n")
    for i, metric in enumerate(("team.mobility_count", "team.cc_count", "team.armor_total")):
        (tmp_path / ("solo-%d.md" % i)).write_text(
            rule % ("Solo %d" % i, metric, "team.supports <= 1"), "utf-8")
    (tmp_path / "their-fliers.md").write_text(
        rule % ("Their fliers", "team.hitscan", "enemy.light_flyers >= 1"), "utf-8")
    scratch = catalog.load(str(tmp_path))
    # Gale flies for red; blue fields Balm as its one support
    solo = engine.evaluate(world, Draft("Harbor Gate", ("Gale",),
                                        ("Anvil", "Mortar", "Rook", "Needle", "Flint", "Balm")),
                           catalog=scratch).to_dict()
    terms = {c["id"]: c for c in solo["contributions"]}
    needs = [terms["solo-%d" % i] for i in range(3)]
    assert all(c["applies"] and c["need"] and c["weighted"] <= 0 for c in needs)
    assert sum(c["weighted"] for c in needs) >= -scoring.NEED_BUDGET - 1e-9
    assert terms["their-fliers"]["need"] is False and terms["their-fliers"]["weighted"] >= 0
    paired = ("Anvil", "Mortar", "Rook", "Needle", "Balm", "Tansy")
    pair = engine.evaluate(world, Draft("Harbor Gate", ("Gale",), paired),
                           catalog=scratch).to_dict()
    assert all(
        not c["applies"] and c["weighted"] == 0
        for c in pair["contributions"] if c["id"].startswith("solo-"))


def test_partners_that_only_pay_together_are_brought_in_together(synthetic_world, tmp_path):
    """One slot at a time, a pair worth nothing apart is never met: each partner
    alone only costs. The playbook here pays one synergy pair, the two
    lowest-standing heroes of their roles, outside the pools. The best six holds
    both, with the locked pick, the ban and the shape kept; the pair step off,
    the search stops short of it."""
    from inference import solver as solver_module
    world = synthetic_world
    # four a role are too few for a pool to leave anyone out once a pair's synergy
    # lifts its standing: three stronger twins of each role's best widen the roster
    next_id = max(world.heroes) + 1
    for role in ("tank", "damage", "support"):
        best = max((h for h in world.heroes.values() if h.role == role and h.released),
                   key=lambda h: h.win)
        for i in range(3):
            twin = dataclasses.replace(best, id=next_id, name="%s %d" % (best.name, i + 2),
                                       win=best.win + 1 + i)
            world.heroes[twin.id] = twin
            world.by_key[name_key(twin.name)] = twin.id
            next_id += 1
    (tmp_path / "shape.md").write_text(ROLE_QUEUE, "utf-8")
    rule = "---\nname: %s\nkind: heuristic\ndirection: maximize\nmetric: %s\nweight: %s\n---\nx\n"
    (tmp_path / "winning.md").write_text(rule % ("Winning", "team.win_mean", 1), "utf-8")
    (tmp_path / "together.md").write_text(rule % ("Together", "team.synergy_edges", 0.5), "utf-8")
    scratch = catalog.load(str(tmp_path))
    locked, banned = [world.hero("Anvil")], [world.hero("Needle")]

    def solver_on(w):              # the playbook alone: the pair is its to pay
        return solver_module.Solver(w, None, red=[], locked=locked, banned=banned,
                                    catalog=scratch, base=OFF, pool_size=2)

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
        assert {a.name, b.name, "Anvil"} <= set(top.names) and "Needle" not in top.names
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


def test_a_ban_does_not_rescale_the_board(synthetic_world):
    """The reference sample fixes every heuristic's [lo, hi], so it must not
    depend on the bans: banning a hero on neither team would otherwise move the
    score of an unchanged six, and `the best six here` would stop being a
    function of the six. Bans screen the candidate field, not the scale. The
    reference playbook scores: under one that scores nothing every six reads
    0 and the check could not fail."""
    from inference import catalog as catalog_module
    from inference import scoring
    from inference import solver as solver_module
    world = synthetic_world
    catalog = catalog_module.load(FIXTURE_PLAYBOOK)
    assert catalog_module.has_scoring_terms(catalog)
    red = ["Mortar", "Gale"]
    six = ["Anvil", "Kite", "Rook", "Needle", "Balm", "Tansy"]
    absent = [
        h.name for h in world.heroes.values()
        if h.released and h.name not in six and h.name not in red][:3]

    def score_under(bans):
        m, red_h, _, bans_h = world.resolve("Harbor Gate", red, [], bans)
        solver = solver_module.Solver(world, m, red=red_h, locked=[], banned=bans_h,
                                      side="attack", catalog=catalog, base=DEFAULT)
        solver.freeze_bounds()
        cand = solver.prepare(scoring.Candidate([world.hero(n) for n in six]))
        return solver.score(cand, detail=False).score

    # the same six, the same number of bans, a different hero banned
    first = score_under([absent[0], absent[2]])
    second = score_under([absent[1], absent[2]])
    assert abs(first - second) < 1e-9, (first, second)


def test_the_order_of_a_six_does_not_decide_the_ranking(synthetic_world):
    """_rank_key's third element breaks ties, so it has to be a property of the
    hero set - in seat order one set keys 720 ways."""
    from inference import scoring
    from inference import solver as solver_module
    world = synthetic_world
    heroes = [world.hero(n) for n in ("Anvil", "Kite", "Rook", "Needle", "Balm", "Tansy")]
    one = scoring.Candidate(heroes)
    other = scoring.Candidate(list(reversed(heroes)))
    one.score = other.score = 1.0
    one.tiebreak = other.tiebreak = 0.5
    assert solver_module.Solver._rank_key(one) == solver_module.Solver._rank_key(other)


def test_a_rule_scales_by_the_metric_it_names(synthetic_world, tmp_path):
    """`confidence:` is an engine field, not a rule: a heuristic names any numeric
    metric and its weight rides on that metric's place between the low and high of
    whatever population the metric actually varies over. Nothing in the code knows
    which metric any rule names. The rule is written here, beside the reference
    playbook, so the test holds whatever the shipped playbook carries."""
    from inference import engine, scoring
    from inference import solver as solver_module
    world = synthetic_world
    # Salt Flats barely leans: poke over dive by a tenth of a point
    world.map("Salt Flats").styles = {
        "poke": StyleScore(1.0, None), "dive": StyleScore(0.9, None),
        "brawl": StyleScore(-1.0, None)}
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
        m, red, _, _ = world.resolve(map_name, ["Anvil", "Gale"], [], [])
        solver = solver_module.Solver(world, m, red=red, locked=[],
                                      side=engine._side(m, "attack"), catalog=playbook,
                                      base=OFF)
        solver.freeze_bounds()
        best = engine.infer(world, Draft(map_name, ("Anvil", "Gale"),
                                         side=engine._side(m, "attack")),
                            top=1, catalog=playbook, base=OFF)
        cand = solver.prepare(scoring.Candidate([world.hero(n) for n in best.blue]))
        solver.score(cand, detail=True)
        return next(c for c in cand.contributions if c["id"] == strategy_id)

    # the map that leans hardest pays the map-style rule; the one that barely leans
    # pays almost none of it, and neither number is written anywhere
    sure = points("Ember Ruins", "fit-the-map-style")
    unsure = points("Salt Flats", "fit-the-map-style")
    assert sure["confidence_raw"] > unsure["confidence_raw"]
    assert sure["weighted"] > unsure["weighted"] * 5


def test_style_ties_break_by_name_so_hash_order_cannot_reach_the_answer(synthetic_world):
    """A set of style names iterates in an order that changes with the process's
    hash seed; the tie-breaks must not depend on it - two views of the same
    heroes whose style sets iterate in opposite orders agree on every metric,
    and the same board solves to the same six twice in a row. Flint carries
    two styles, so its set has two orders."""
    from inference import engine
    world = synthetic_world
    heroes = [world.hero(n) for n in ("Anvil", "Kite", "Flint", "Needle", "Balm", "Sorrel")]
    forward = team_metrics(world, heroes, world.map("Ember Ruins"), [])

    from facts import model

    class Reversed(model.Hero):                # the same hero, its styles iterated backwards
        def __init__(self, hero):
            self.__dict__ = dict(hero.__dict__)
            self.styles = sorted(hero.styles, reverse=True)   # the other iteration order
    backward = team_metrics(world, [Reversed(h) for h in heroes], world.map("Ember Ruins"), [])
    for key in ("style_top", "style_lean", "style_counts", "style_fit"):
        assert forward[key] == backward[key], key
    ember = world.map("Ember Ruins")
    derived = dict(ember.styles)
    ember.styles = {"poke": StyleScore(1.0, None), "dive": StyleScore(0.2, None),
                    "brawl": StyleScore(1.0, None)}
    try:
        assert ember.style_top == "brawl" and ember.style_margin == 0
    finally:
        ember.styles = derived
    fix = catalog.load(FIXTURE_PLAYBOOK)
    once = engine.infer(world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",)), catalog=fix)
    twice = engine.infer(world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",)), catalog=fix)
    assert once.blue == twice.blue and abs(once.score - twice.score) < 1e-12


def test_a_board_confidence_reads_the_boards_own_ban_count(synthetic_world, tmp_path):
    """A confidence metric of the board is read over every map, and every map
    reads it with this board's bans: map.bans is the count made in this match,
    whatever map the population is drawn from."""
    from inference import scoring
    from inference import solver as solver_module
    world = synthetic_world
    shutil.copytree(FIXTURE_PLAYBOOK, tmp_path, dirs_exist_ok=True)
    (tmp_path / "scale-by-the-bans.md").write_text(
        "---\nname: Pick into what the map rewards once the bans are in\nkind: heuristic\n"
        "category: map\nmetric: team.style_fit\ndirection: maximize\nweight: 2.5\n"
        "when: map.known == 1\nconfidence: map.bans\n---\n"
        "# Pick into what the map rewards once the bans are in\n\n"
        "The share of the six tagged with the style the map rewards, weighed by how "
        "many bans are made.\n", encoding="utf-8")
    playbook = catalog.load(str(tmp_path))
    m, red, _, banned = world.resolve("Harbor Gate", ["Mortar", "Gale"], [],
                                      ["Needle", "Rook"])
    solver = solver_module.Solver(world, m, red=red, locked=[], banned=banned, side="attack",
                                  catalog=playbook, base=DEFAULT)
    solver.freeze_bounds()
    assert solver.bounds["scale-by-the-bans" + scoring.CONFIDENCE_KEY] == (2.0, 2.0)


def test_merged_slices_bound_a_confidence_metric_as_one_process_does(synthetic_world, tmp_path):
    """A slice in which no six values a heuristic leaves out its confidence
    bounds as well as its own, so merging it adds nothing: a confidence metric
    below zero on every six that values it keeps its high below zero, as the
    bounds drawn in one process do."""
    from inference import parallel, scale, scoring
    with open(os.path.join(FIXTURE_PLAYBOOK, "meta-strength.md"), encoding="utf-8") as handle:
        text = handle.read()
    (tmp_path / "meta-strength.md").write_text(
        text.replace("weight: 1\n", "weight: 1\nconfidence: team.pick_mass\n", 1),
        encoding="utf-8")
    playbook = catalog.load(str(tmp_path))
    assert [h.confidence for h in playbook] == ["team.pick_mass"]
    objective = scoring.Objective(synthetic_world, None, red=[], catalog=playbook, base=DEFAULT)
    valued = []
    for raw, sure in ((0.4, -2.0), (0.7, -1.0)):
        cand = scoring.Candidate([])
        cand.raw, cand.confidence = [raw], [sure]
        valued.append(cand)
    unvalued = scoring.Candidate([])
    unvalued.raw, unvalued.confidence = [None], [None]
    merged = parallel._widen(parallel._widen({}, scale._bounds_over(objective, valued)),
                             scale._bounds_over(objective, [unvalued]))
    assert merged == scale._bounds_over(objective, [*valued, unvalued])
    assert merged["meta-strength" + scoring.CONFIDENCE_KEY] == scoring.Interval(-2.0, -1.0)


def test_a_roster_with_fewer_legal_sixes_than_the_reference_is_sampled_whole(synthetic_world):
    """Twelve heroes, four a role, hold fewer distinct sixes than REFERENCE_SIZE
    asks for. The reference is then every legal six once, in the seeded order,
    where the draw used to spin forever looking for more."""
    from inference import scale, scoring
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    legal = {frozenset(h.id for h in six) for six in legal_sixes(synthetic_world, playbook)}
    objective = scoring.Objective(synthetic_world, None, red=[], catalog=playbook, base=DEFAULT)
    drawn = scale.sample(objective)
    assert len(legal) < scale.REFERENCE_SIZE
    assert [c.key for c in drawn] == [c.key for c in scale.sample(objective)]
    assert sorted(sorted(c.key) for c in drawn) == sorted(sorted(six) for six in legal)
