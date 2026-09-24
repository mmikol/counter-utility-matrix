"""The inference layer: the expression language and catalog are pure; the
solver and evaluation run against the built database."""

import copy
import os
import shutil

import pytest

from db import Refusal
from inference import catalog
from inference.engine import BrokenProcessPool
from inference.expr import Expr, ExprError
from tests.inference import FIXTURE_PLAYBOOK
from ui.facts import board_facts, compute
from ui.facts.draft import MAX_TANKS, Draft
from ui.facts.team import team_metrics

# --- the expression language (pure) --------------------------------------

def test_expressions_read_dotted_names_and_arithmetic():
    ns = {"team": {"tanks": 1, "hitscan": 3}, "params": {"X": 2}}
    assert Expr("team.tanks == 1 and team.hitscan >= params.X").evaluate(ns) is True
    assert Expr("min(team.hitscan, 2) * 1.5").evaluate(ns) == 3.0
    assert Expr("team.missing + 1").evaluate(ns) == 1          # unknown reads 0
    assert Expr("'dive' if team.tanks else 'brawl'").evaluate(ns) == "dive"
    assert Expr("team.tanks / 0").evaluate(ns) == 0.0


def test_expressions_refuse_anything_beyond_the_whitelist():
    for bad in ("__import__('os')", "team.__class__", "[x for x in y]",
                "lambda: 1", "open('f')", "team.tanks = 2"):
        with pytest.raises(ExprError):
            Expr(bad).evaluate({"team": {}})
    # an operator outside the whitelist's tuples is refused as the node it sits in
    for bad, node in (("team.tanks | 1", "BinOp"), ("~team.tanks", "UnaryOp")):
        with pytest.raises(ExprError, match="unsupported syntax %s" % node):
            Expr(bad)


def test_expression_names_are_the_full_dotted_keys():
    assert Expr("team.tanks + enemy.flyers * params.K").names == [
        "enemy.flyers", "params.K", "team.tanks"]


# --- the catalog (pure) -----------------------------------------------------

def test_frontmatter_parses_scalars_lists_and_params():
    meta, body = catalog.parse_frontmatter(
        "---\nname: X\nweight: 2.5\nsoft: true\ntags: [a, b]\nn: -4\nf: 1e3\nw: word\nz: ~\n"
        "params:\n  K: 3\n---\n# X\nbody\n")
    assert meta == {"name": "X", "weight": 2.5, "soft": True, "tags": ["a", "b"], "n": -4,
                    "f": 1000.0, "w": "word", "z": None, "params": {"K": 3}}
    assert type(meta["n"]) is int and type(meta["f"]) is float
    assert body == "# X\nbody"


def test_the_reference_and_the_live_playbooks_are_valid_and_reference_real_metrics():
    live = catalog.load()                       # the user's playbook: whatever it holds today
    assert live and {h.kind for h in live} <= set(catalog.KINDS)
    assert all(h.metric in compute.registry() for h in live if h.kind == "heuristic")
    cat = catalog.load(FIXTURE_PLAYBOOK)        # the reference: every kind and every form
    kinds = {h.kind for h in cat}
    assert kinds == set(catalog.KINDS) == {"constraint", "heuristic", "assumption"}
    forms = {h.form for h in cat}
    assert forms == {"limit", "scored", "heuristic", "assumption"}
    assert all(h.form == "heuristic" for h in cat if h.kind == "heuristic")
    assert all(h.form == "assumption" and not h.solver_reads for h in cat
               if h.kind == "assumption")
    assert {h.id for h in cat if h.kind == "assumption"} >= {"optimal-play", "vintage", "objective"}
    registry = compute.registry()
    for h in cat:
        if h.kind == "heuristic":
            assert h.metric in registry and h.metric not in compute.TEXT_METRICS
        for e in (h.when, h.require, h.bonus, h.penalty):
            for name in (e.names if e else []):
                assert name in registry or name[7:] in h.params, (h.id, name)
    assert any(h.id == "open-queue-tanks" for h in cat)


def test_catalog_rejects_a_goal_on_an_unknown_metric(tmp_path):
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\nkind: heuristic\ndirection: maximize\nmetric: team.nope\n---\nx\n",
        "utf-8")
    with pytest.raises(catalog.CatalogError, match="not a registered fact key"):
        catalog.load(str(tmp_path))
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\nkind: constraint\nwhen: team.tanks > params.T\nbonus: 1\n---\nx\n",
        "utf-8")
    with pytest.raises(catalog.CatalogError, match="params"):
        catalog.load(str(tmp_path))


class _Call:
    """One orchestration call, as the trace records it."""

    def __init__(self, what, **kw):
        self.what, self.kw = what, kw

    def __eq__(self, other):
        return (self.what, self.kw) == (other.what, other.kw)

    def __repr__(self):
        return "%s(%s)" % (self.what, ", ".join("%s=%r" % kv for kv in sorted(self.kw.items())))


def _traced_board(monkeypatch, *, parallel, breaks_after=None, blue=("Ana",), red=("Zarya",)):
    """Run board()'s orchestration with every call it makes stubbed out, and
    return the trace. The World, the facts and the solver never run: what is
    under test is the sequence, which is the one thing the pooled and the
    in-process passes have to agree on."""
    from inference import engine
    trace = []

    class Split:
        def __init__(self, pool, world, catalog, spec, weights, top, slices,
                     bounds=None, standing=None):
            self.spec, self.bounds, self.standing = spec, bounds, standing
            trace.append(_Call("split", locked=spec.draft.blue, enemy=spec.draft.red))

        def _step(self, name):
            trace.append(_Call(name, enemy=self.spec.draft.red))
            if breaks_after is not None and len(trace) >= breaks_after:
                raise BrokenProcessPool("a worker died")

        def rank_roster(self):
            self._step("rank_roster")

        def sweep(self):
            self._step("sweep")

        def merge(self):
            self._step("merge")

        def solved(self):
            self._step("solved")
            return "solved"

        def swept(self):
            self._step("swept")
            return "swept"

    class Fake:
        kind, blue, red, score, seconds = "infer", ["A", "B"], [], 1.0, 0.0
        picks, contributions, partial, facts = [], [], False, None

        def resolve(self, *a):
            return None, [], [], []

        def scale_to(self, best):
            pass

    def optimal(world, draft, *, solved, seat, **kw):
        trace.append(_Call("infer", enemy=draft.red, locked=draft.blue, solved=solved,
                           seat=seat))
        return engine._Optimal(Fake(), None)

    def current(world, draft, *, swept, seat, **kw):
        trace.append(_Call("current", enemy=draft.red, picks=draft.blue, swept=swept,
                           seat=seat))
        return Fake()

    def countered(world, draft, *, solved, swept, **kw):
        trace.append(_Call("countered", against=draft.red, picks=draft.blue,
                           solved=solved, swept=swept))
        return Fake()

    monkeypatch.setattr(engine, "parallel_available", lambda catalog=None: parallel)
    monkeypatch.setattr(engine, "_workers", lambda: engine.Workers("pool", 6))
    monkeypatch.setattr(engine, "_drop_workers", lambda: trace.append(_Call("drop_workers")))
    monkeypatch.setattr(engine, "_Split", Split)
    monkeypatch.setattr(engine, "_optimal", optimal)
    monkeypatch.setattr(engine, "_current", current)
    monkeypatch.setattr(engine, "_countered", countered)
    monkeypatch.setattr(engine, "_momentum", lambda *a, **kw: {"verdict": "-"})
    monkeypatch.setattr(engine, "_plan", lambda *a: "-")
    monkeypatch.setattr(engine, "legal_shapes", lambda catalog: [])
    monkeypatch.setattr(engine.compute, "expected_picks", lambda *a, **kw: [])
    engine.board(Fake(), Draft(None, tuple(red), tuple(blue)),
                 catalog=catalog.load(FIXTURE_PLAYBOOK))
    return trace


def test_the_pooled_and_the_in_process_board_run_one_orchestration(monkeypatch):
    """The six calls are written once. Pooled, each is handed its split's
    result; in this process every split is None and the call searches for
    itself. Nothing else about the sequence may differ."""
    pooled = _traced_board(monkeypatch, parallel=True)
    alone = _traced_board(monkeypatch, parallel=False)
    assert [c.what for c in alone] == ["infer", "infer", "current", "current",
                                       "infer", "countered"]
    assert all(c.kw["solved"] is None for c in alone if c.what == "infer")
    assert all(c.kw["swept"] is None for c in alone if c.what in ("current", "countered"))
    # the same six calls, in the same order, with the same boards
    def shape(trace):
        return [(c.what, {k: v for k, v in c.kw.items() if k not in ("solved", "swept")})
                for c in trace if c.what in ("infer", "current", "countered")]
    assert shape(pooled) == shape(alone)
    # pooled, each call takes its split's work instead of searching
    assert [c.kw["solved"] for c in pooled if c.what == "infer"] == ["solved"] * 3


def test_a_dying_worker_reruns_the_same_board_in_this_process(monkeypatch):
    """A BrokenProcessPool anywhere in the pooled pass drops the pool and runs
    the identical sequence here - not a second, differently written one."""
    alone = _traced_board(monkeypatch, parallel=False)
    for breaks_after in (1, 4, 8, 12):
        trace = _traced_board(monkeypatch, parallel=True, breaks_after=breaks_after)
        assert _Call("drop_workers") in trace, breaks_after
        after = trace[[c.what for c in trace].index("drop_workers") + 1:]
        assert after == alone, (breaks_after, after)


# --- the solver against the built database ------------------------------------

@pytest.fixture(scope="module")
def kings_row_board(world):
    """The board the tests read most - King's Row, Zarya and Pharah revealed, Ana and
    Reinhardt locked, the reference playbook - solved once per module (a caller's
    catalog keeps the solve in one process)."""
    from inference import engine
    return engine.board(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana", "Reinhardt")),
                        catalog=catalog.load(FIXTURE_PLAYBOOK))


@pytest.mark.invariant
def test_infer_keeps_locked_picks_and_the_open_queue_shape(world):
    from inference import engine
    r = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",)),
                     catalog=catalog.load(FIXTURE_PLAYBOOK))
    assert len(r.blue) == 6 and "Ana" in r.blue
    roles = [world.hero(n).role for n in r.blue]
    assert roles.count("tank") <= 2
    assert r.considered > 100 and r.score > 0
    assert any(p["hero"] == "Ana" and p["locked"] for p in r.picks)
    # every pick cites facts the board for (map, red, the five) shows
    assert r.facts.draft.blue == tuple(r.blue)
    ids = {f.id for f in r.facts.facts}
    for p in r.picks:
        assert p["evidence"] and set(p["evidence"]) <= ids
    # coverage of both enemies is worth 3 points, and the optimum takes them
    cov = next(c for c in r.contributions if c["id"] == "coverage")
    assert cov["raw"] == 1.0 and cov.get("fact")


@pytest.mark.invariant
def test_infer_honours_a_hitscan_answer_to_a_flier(world):
    from inference import engine
    r = engine.infer(world, Draft("Havana", ("Pharah", "Mercy")),
                     catalog=catalog.load(FIXTURE_PLAYBOOK))
    assert any(world.hero(n).hitscan for n in r.blue)
    anti = next(c for c in r.contributions if c["id"] == "anti-air")
    assert anti["applies"] and anti["ok"]


@pytest.mark.invariant
def test_evaluate_ranks_a_full_six_against_the_field(world):
    from inference import engine
    six = ("Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio")
    r = engine.evaluate(world, Draft("King's Row", ("Zarya", "Pharah"), six))
    assert r.rank >= 1 and r.kind == "evaluate" and len(r.picks) == 6
    with pytest.raises(Refusal, match="exactly 6"):
        engine.evaluate(world, Draft(blue=("Ana",)))


@pytest.mark.invariant
def test_a_board_no_six_satisfies_is_refused_by_infer_and_evaluate_alike(world, tmp_path):
    """A hard limit no six can meet leaves no legal shape, so the field is
    empty: infer refuses the board, and evaluate refuses it the same way
    instead of ranking a six first among nothing."""
    from inference import engine
    (tmp_path / "seven-tanks.md").write_text(
        "---\nname: seven tanks\nkind: constraint\nrequire: team.tanks == 7\n---\nx\n", "utf-8")
    scratch = catalog.load(str(tmp_path))
    with pytest.raises(Refusal, match="relax a constraint"):
        engine.infer(world, Draft("King's Row", ("Zarya",)), catalog=scratch)
    with pytest.raises(Refusal, match="relax a constraint"):
        engine.evaluate(world, Draft("King's Row", ("Zarya",),
                                     ("Reinhardt", "D.Va", "Ashe", "Sojourn", "Ana", "Kiriko")),
                        catalog=scratch)


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
def test_infer_never_drafts_a_banned_hero(world):
    from inference import engine
    r = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",),
                                  ("Widowmaker", "Bastion", "Reinhardt")))
    assert not {"Widowmaker", "Bastion", "Reinhardt"} & set(r.blue)
    assert r.bans == ["Widowmaker", "Bastion", "Reinhardt"] and "banned" in r.rendered()
    assert r.facts.draft.bans == tuple(r.bans)
    with pytest.raises(Refusal, match="banned this match"):
        engine.infer(world, Draft(None, ("Zarya",), ("Ana",), ("Zarya",)))


@pytest.mark.invariant
def test_board_solves_both_seats_on_opposite_sides_and_scores_the_current(world):
    from inference import engine
    fix = catalog.load(FIXTURE_PLAYBOOK)        # the reference playbook has the side rules
    b = engine.board(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",), side="attack"),
                     catalog=fix)
    blue, red, cur = b.blue, b.red, b.current
    assert blue.seat == "blue" and blue.side == "attack" and blue.locked == []
    absolute = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah"), (), side="attack"),
                            catalog=fix)
    assert blue.blue == absolute.blue                     # blue's optimal ignores your picks
    assert red.seat == "red" and red.side == "defense" and len(red.blue) == 6
    # red's optimal: their best counter to ours
    assert red.locked == [] and red.red == ["Ana"]
    theirs = engine.infer(world, Draft("King's Row", ("Ana",), (), side="defense"), catalog=fix)
    assert red.blue == theirs.blue
    assert cur.kind == "current" and cur.partial and cur.blue == ["Ana"]
    assert cur.contributions and cur.score is not None
    rc = b.red_current                                  # their comp as revealed, scored vs ours
    assert rc.seat == "red"
    assert set(rc.blue) == {"Zarya", "Pharah"}
    assert rc.red == ["Ana"]
    assert rc.partial
    assert rc.to_dict()["normalized"] is None        # a partial team has no share
    assert b.countered is not None and b.countered.kind == "countered"
    fill = b.fill                                       # the empty slots, filled around Ana
    assert fill.kind == "fill"
    assert fill.locked == ["Ana"]
    assert len(fill.blue) == 6
    assert "Ana" in fill.blue
    assert [p["locked"] for p in fill.picks].count(True) == 1
    assert 0 < fill.to_dict()["normalized"] <= 100
    around = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",), side="attack"),
                          catalog=fix)
    assert fill.blue == around.blue
    mo = b.momentum
    assert set(mo) >= {"blue", "red", "countered", "verdict", "partial"} and mo["partial"]
    # blue is half-drafted, so its share is read through the fill - the best six
    # reachable from its picks - not off the picks alone. Red has no fill computed,
    # so its share keeps the older reading; both dicts report no share of their own.
    assert mo["blue"] == fill.to_dict()["normalized"]
    assert mo["red"] is not None
    assert cur.to_dict()["normalized"] is None and rc.to_dict()["normalized"] is None
    assert ("ahead by" in mo["verdict"] or mo["verdict"].startswith("even"))
    assert "best counter" in mo["verdict"]
    # prose: the ground, what to play, them, the family
    plan = b.plan
    assert plan.startswith("King's Row is a Hybrid map: a capture point and then the payload path")
    assert "You are attacking: you have to break their hold" in plan
    assert "The map rewards %s" % world.map("King's Row").style_top in plan
    assert "Their 2 picks so far (Zarya, Pharah)" in plan and "answer" in plan
    assert "If you stray from the six, stay in its family. Tanks: " in plan
    assert "Above all: " in plan
    assert plan.endswith("Based on: the rates and counters, the map, the side,"
                         " red's 2 revealed picks.")
    d = b.to_dict()
    assert d["side"] == "attack" and d["red"]["seat"] == "red" and d["current"]["partial"]
    assert d["red_current"]["seat"] == "red"
    assert d["momentum"]["verdict"] == mo["verdict"]
    assert d["plan"] == plan
    assert d["fill"]["kind"] == "fill" and "the rest filled" in b.rendered()
    assert "current comp" in b.rendered() and "momentum:" in b.rendered()
    # the side constraints fire on the right seat
    ids = {c["id"] for c in blue.contributions if c.get("applies")}
    assert "attack-breaks-the-hold" in ids and "defense-holds-the-ground" not in ids
    ids = {c["id"] for c in red.contributions if c.get("applies")}
    assert "defense-holds-the-ground" in ids


def test_weights_override_a_heuristic_for_one_board_and_never_the_file():
    """The playbook tab's sliders: `id:value` strings or a mapping become
    weights clamped to the file's range; the catalog's heuristic carries the
    override in a copy, the loaded one and its file are untouched, and a
    constraint or an unknown id is ignored."""
    parsed = catalog.parse_weights(["a:2", "b:11", "c:-1"])
    assert parsed == {"a": 2.0, "b": 10.0, "c": 0.0}
    assert catalog.parse_weights({"a": "3.5"}) == {"a": 3.5}
    # a malformed weight is refused, never dropped
    for malformed, said in ((["nonsense"], "id:value"), (["d:x"], "not a number"),
                            ({"e": None}, "not a number")):
        with pytest.raises(Refusal, match=said):
            catalog.parse_weights(malformed)
    cat = catalog.load(FIXTURE_PLAYBOOK)
    heuristic = next(h for h in cat if h.kind == "heuristic")
    limit = next(h for h in cat if h.form == "limit")
    before = heuristic.weight
    over = catalog.weighted(cat, {heuristic.id: 7.5, limit.id: 9, "no-such": 1})
    assert next(h for h in over if h.id == heuristic.id).weight == 7.5
    assert heuristic.weight == before                        # the loaded one is untouched
    assert next(h for h in over if h.id == limit.id) is limit  # a constraint's stays its own
    assert catalog.weighted(cat, {}) is cat and len(over) == len(cat)


@pytest.mark.invariant
def test_the_board_scores_under_the_weights_it_is_given(world, kings_row_board):
    """A weight set on the board changes the score, every result says the
    weights it was scored under, and the file is untouched."""
    from inference import engine
    plain = kings_row_board
    fix = catalog.load(FIXTURE_PLAYBOOK)
    # a heuristic that actually moves this comp's score (one at the reference floor would not)
    moving = next(c["id"] for c in plain.current.contributions
                  if c["kind"] == "heuristic" and c.get("weighted"))
    heuristic = next(h for h in fix if h.id == moving)
    weights = {heuristic.id: 10.0 if heuristic.weight < 10 else 0.5}
    tilted = engine.board(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana", "Reinhardt")),
                          catalog=fix, weights=weights)
    assert tilted.current.to_dict()["weights"][heuristic.id] == weights[heuristic.id]
    assert plain.current.to_dict()["weights"][heuristic.id] == heuristic.weight
    assert tilted.current.score != plain.current.score
    assert next(h for h in catalog.load(FIXTURE_PLAYBOOK)
                if h.id == heuristic.id).weight == heuristic.weight


@pytest.mark.invariant
def test_fight_odds_pit_the_two_shares_against_each_other(world, kings_row_board):
    """Both seats scored: each side's odds are its share over the two shares'
    sum, the pair splits 100, and the verdict says so; one seat unscored or
    empty: no odds."""
    from inference import engine
    b = kings_row_board.to_dict()
    mo = b["momentum"]
    n, m = mo["blue"], mo["red"]
    assert isinstance(n, int) and isinstance(m, int) and n + m > 0
    blue_odds = round(100.0 * n / (n + m))
    assert mo["odds"] == {"blue": blue_odds, "red": 100 - blue_odds}
    assert "fight odds blue %d%%, red %d%%" % (blue_odds, 100 - blue_odds) in mo["verdict"]
    alone = engine.board(world, Draft("King's Row", ("Zarya", "Pharah")),
                         catalog=catalog.load(FIXTURE_PLAYBOOK)).to_dict()
    assert alone["momentum"]["blue"] is None and alone["momentum"]["odds"] is None


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
    if any(world.hero(name).flyer and world.hero(name).role != "tank"
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


@pytest.mark.invariant
def test_legal_shapes_follow_the_playbook_and_the_board_carries_them(world):
    """The roster enforces what the shape limits allow: the two-tank limit
    means no triple the solver would search seats a third tank, and the
    board says so in a form the script can read."""
    from inference import engine
    from inference.scoring import legal_shapes
    cat = catalog.load(FIXTURE_PLAYBOOK)
    shapes = legal_shapes(cat)
    assert shapes and all(t + d + s == 6 for t, d, s in shapes)
    assert (2, 2, 2) in shapes and all(t <= 2 for t, _, _ in shapes)
    assert (3, 2, 1) not in shapes
    seated = legal_shapes(cat, {"tank": 2, "damage": 3, "support": 0})
    assert seated and all(t == 2 and d >= 3 for t, d, _ in seated)
    b = engine.board(world, Draft("King's Row", ("Zarya",), ("Ana",)), catalog=cat)
    assert b.shapes == [list(s) for s in shapes]
    d = b.to_dict()
    assert d["shapes"] == b.shapes
    # red's likely six rides along - static: the map and the meta, not their reveal
    assert d["expected"]["kind"] == "expected" and "Zarya" not in d["expected"]["blue"]
    assert len(d["expected"]["picks"]) == 6 and all(p["why"] for p in d["expected"]["picks"])
    assert not any(p["locked"] for p in d["expected"]["picks"])


@pytest.mark.invariant
def test_the_queue_caps_tanks_at_two_whatever_the_playbook_holds(world):
    """The shipped playbook writes no shape limit and scores nothing, so every
    six ties and the map's win rates rank the pools - tanks, on most maps. The
    queue's own limit binds all the same: no six the board shows fields a
    third tank, the shapes the roster enforces stop at two, and a third tank
    is refused as the queue's."""
    from inference import engine
    shipped = catalog.load()
    assert not any(h.form == "limit" for h in shipped)       # the cap is the engine's
    for map_name, blue in (("Blizzard World", []), ("Esperança", []),
                           ("King's Row", ["Winston", "D.Va"])):
        d = engine.board(world, Draft(map_name, (), tuple(blue)), catalog=shipped).to_dict()
        sixes = [d[seat]["blue"] for seat in ("blue", "red", "fill", "expected") if d[seat]]
        assert len(sixes) == (4 if blue else 3)
        for six in sixes:
            assert sum(world.hero(n).role == "tank" for n in six) <= MAX_TANKS, (map_name, six)
        assert max(t for t, _, _ in d["shapes"]) == MAX_TANKS
    for blue in (["Winston", "D.Va", "Reinhardt"], ["Winston", "D.Va", "Reinhardt", "Ana"]):
        with pytest.raises(Refusal, match="the queue allows at most 2 tanks"):
            engine.board(world, Draft("King's Row", (), tuple(blue)), catalog=shipped)
    with pytest.raises(Refusal, match="the queue allows at most 2 tanks"):
        engine.evaluate(world, Draft("King's Row", (),
                                     ("Winston", "D.Va", "Reinhardt", "Ana", "Kiriko", "Ashe")),
                        catalog=shipped)


@pytest.mark.invariant
def test_the_board_refuses_a_team_of_seven(world):
    """engine.board is what every door reaches, the MCP tool with no wire to
    parse among them: a seventh pick on either team is refused before any
    search, where it used to be scored as a seven-hero comp."""
    from inference import engine
    fix = catalog.load(FIXTURE_PLAYBOOK)
    seven = ["Ana", "Kiriko", "Lúcio", "Tracer", "Genji", "Sojourn", "Ashe"]
    with pytest.raises(Refusal, match="more than 6 red picks"):
        engine.board(world, Draft("King's Row", tuple(seven), ()), catalog=fix)
    with pytest.raises(Refusal, match="more than 6 blue picks"):
        engine.board(world, Draft("King's Row", (), tuple(seven)), catalog=fix)


@pytest.mark.invariant
def test_blue_counters_the_likely_six_until_red_reveals_a_pick(world, monkeypatch):
    """With no red pick the board solves blue against red's likely six, so the
    opening suggestion is a counter to what the map and the meta say red
    fields; the first reveal replaces that with red's actual picks."""
    from inference import engine
    monkeypatch.setattr(engine, "parallel_available", lambda catalog=None: False)
    m = world.map("King's Row")
    likely = [p["hero"] for p in compute.expected_picks(world, m)]
    b = engine.board(world, Draft("King's Row", (), ("Ana",)))
    assert b.blue.red == likely and b.current.red == likely and b.fill.red == likely
    assert b.expected.blue == likely and b.expected.kind == "expected"
    assert [p["hero"] for p in b.expected.picks] == likely
    assert "their likely starting comp" in b.rendered()
    revealed = engine.board(world, Draft("King's Row", ("Zarya",), ("Ana",)))
    assert revealed.blue.red == ["Zarya"] and revealed.current.red == ["Zarya"]
    assert revealed.expected.blue == likely                      # static


@pytest.mark.invariant
def test_board_ranks_a_full_six_and_ignores_sides_on_control(world):
    from inference import engine
    fix = catalog.load(FIXTURE_PLAYBOOK)
    six = ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"]
    b = engine.board(world, Draft("Ilios", ("Pharah",), tuple(six), side="attack"), catalog=fix)
    assert b.side == "" and b.blue.side == "" and b.red.side == ""
    assert b.current.kind == "evaluate" and b.current.rank >= 1
    assert set(b.current.blue) == set(six)
    assert b.blue.locked == [] and b.blue.to_dict()["normalized"] == 100
    assert 0 <= b.current.to_dict()["normalized"] <= 100      # against the absolute optimal
    b = engine.board(world, Draft(), catalog=fix)
    assert not b.current.blue and b.current.partial
    # nothing locked: the optimal is the fill
    assert b.countered is None and b.fill is None
    assert b.momentum["verdict"] == "no picks yet on either side"
    assert b.momentum["blue"] is None and b.momentum["red"] is None
    assert b.plan.startswith("No map yet, so this is the meta's best six")
    assert b.plan.endswith("Based on: the rates and counters.")
    assert len(b.blue.blue) == 6                      # the meta's best six, before any map
    b = engine.board(world, Draft("Ilios", (), (), ("Widowmaker",)), catalog=fix)
    assert b.plan.endswith("the map, 1 ban.") and b.plan.count("\n") >= 2
    assert b.plan.startswith("Ilios is a Control map: one point in three arenas")
    assert "The map rewards %s" % world.map("Ilios").style_top in b.plan


@pytest.mark.invariant
def test_scores_share_one_scale_per_board(world):
    # infer, evaluate and the current comp normalise against the same
    # seeded reference sample, so the same six scores the same everywhere
    from inference import engine
    fix = catalog.load(FIXTURE_PLAYBOOK)       # a rich playbook: alternatives fall below the best
    # no lock: evaluate ranks a six against the whole unlocked field, and the best six
    # that keeps a locked pick need not be the best of that field
    r = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah")), catalog=fix)
    e = engine.evaluate(world, Draft("King's Row", ("Zarya", "Pharah"), tuple(r.blue)), catalog=fix)
    assert abs(r.score - e.score) < 1e-9 and e.rank == 1
    held = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",)), catalog=fix)
    again = engine.evaluate(world, Draft("King's Row", ("Zarya", "Pharah"), tuple(held.blue)),
                            catalog=fix)
    assert "Ana" in held.blue and abs(held.score - again.score) < 1e-9
    assert r.to_dict()["normalized"] == 100 and e.to_dict()["normalized"] == 100
    assert all(0 <= a["normalized"] <= 100 for a in r.alternatives)
    assert r.alternatives[0]["score"] < r.score        # below the optimum, if only by a hair
    assert r.alternatives[0]["normalized"] <= 100
    best = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah")), catalog=fix)
    b = engine.board(world, Draft("King's Row", ("Zarya", "Pharah"), tuple(best.blue)), catalog=fix)
    assert abs(b.current.score - best.score) < 1e-9 and b.blue.blue == best.blue
    assert b.current.to_dict()["normalized"] == 100 and b.red.to_dict()["normalized"] == 100
    # around Ana
    b = engine.board(world, Draft("King's Row", ("Zarya", "Pharah"), tuple(r.blue)), catalog=fix)
    assert b.blue.blue == best.blue and b.current.to_dict()["normalized"] <= 100
    again = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",)), pool_size=4,
                         catalog=fix)
    rescored = engine.evaluate(world, Draft("King's Row", ("Zarya", "Pharah"), tuple(again.blue)),
                               catalog=fix)
    assert abs(again.score - rescored.score) < 1e-9


def test_a_constraint_is_a_limit_or_scored_and_an_assumption_is_prose(tmp_path):
    def load_one(text):
        (tmp_path / "x.md").write_text(text, encoding="utf-8")
        return catalog.load(str(tmp_path))[0]
    limit = load_one("---\nname: l\nkind: constraint\nrequire: team.tanks <= 2\n---\nx\n")
    assert limit.form == "limit"
    assert load_one("---\nname: s\nkind: constraint\nbonus: team.tanks\n---\nx\n").form == "scored"
    assert load_one("---\nname: p\nkind: assumption\n---\nx\n").form == "assumption"
    # awaiting /strategy
    assert load_one("---\nname: d\nkind: constraint\n---\nx\n").form == "draft"
    assert load_one("---\nname: d\nkind: heuristic\n---\nx\n").pending
    assert not load_one("---\nname: p\nkind: assumption\n---\nx\n").pending
    assert load_one("---\nname: g\nkind: heuristic\ndirection: maximize\nmetric: team.tanks\n"
                    "---\nx\n").form == "heuristic"
    for bad in ("---\nname: b\nkind: constraint\nrequire: team.tanks <= 2\nbonus: 1\n---\nx\n",
                "---\nname: b\nkind: constraint\nmetric: team.tanks\n---\nx\n",
                "---\nname: b\nkind: heuristic\ndirection: maximize\nmetric: team.tanks\n"
                "require: team.tanks <= 2\n---\nx\n",
                "---\nname: b\nkind: constraint\nrequire: team.tanks <= 2\nsoft: true\n---\nx\n",
                "---\nname: b\nkind: rule\nrequire: team.tanks <= 2\n---\nx\n",
                "---\nname: b\nkind: assumption\nrequire: team.tanks <= 2\n---\nx\n",
                "---\nname: b\nkind: goal\ndirection: maximize\nmetric: team.tanks\n---\nx\n",
                "---\nname: b\nkind: strategy\n---\nx\n"):
        with pytest.raises(catalog.CatalogError):
            load_one(bad)


def test_the_sandbox_refuses_what_would_hang_or_exhaust_it():
    from inference.expr import Expr, ExprError
    for bomb in ("9 ** 9 ** 9", "2 ** team.tanks", "'a' * 1000000000", "'x' + 'y'",
                 "'" + "s" * 201 + "' == team.style_lean", "-" * 45 + "1"):
        with pytest.raises(ExprError):
            Expr(bomb)
    assert Expr("team.tanks ** 2").evaluate({"team": {"tanks": 3}}) == 9
    assert Expr("team.style_lean == 'dive'").evaluate({"team": {"style_lean": "dive"}}) is True


def test_the_momentum_verdict_reads_the_two_current_comps():
    from inference import engine
    fix = catalog.load(FIXTURE_PLAYBOOK)

    def comp(blue, score, best, partial=False):
        return engine.Result(kind="current", map_name=None, red=[], blue=blue, locked=blue,
                             catalog=fix, score=score, best=best, partial=partial)
    even = engine._momentum(comp(["a"], 8, 10), comp(["b"], 7.8, 10), None)
    assert even["verdict"].startswith("even") and even["blue"] == 80 and even["red"] == 78
    blue = engine._momentum(comp(["a"] * 6, 9, 10), comp(["b"] * 6, 5, 10),
                            comp(["a"] * 6, 3, 10))
    assert blue["verdict"].startswith("blue ahead by 40") and blue["countered"] == 30
    assert "your picks hold 30 / 100" in blue["verdict"] and not blue["partial"]
    red = engine._momentum(comp(["a"], 2, 10, partial=True), comp(["b"] * 6, 9, 10), None)
    assert red["verdict"].startswith("red ahead by 70") and "(partial picks)" in red["verdict"]
    only_red = engine._momentum(comp([], 0, 10), comp(["b"], 5, 10), None)
    assert only_red["verdict"].startswith("red has revealed")


@pytest.mark.invariant
def test_the_plan_names_every_maps_derived_style(world, kings_row_board):
    """Every map's plan names the style its rates reward and cites no note: a
    map has none. One board is solved through the public path; the other maps'
    plans are composed from that board's optimal."""
    from inference import engine
    blue_r = kings_row_board.blue
    for m in world.maps.values():
        assert m.style_top and all(note is None for _, note in m.styles.values()), m.name
        plan = (kings_row_board.plan if m.name == "King's Row"
                else engine._plan(world, m, "", [], [], blue_r))
        assert "The map rewards %s" % m.style_top in plan, m.name
        assert "archetype" not in plan and "authored" not in plan, m.name
    assert engine._and(["A"]) == "A" and engine._and(["A", "B", "C"]) == "A, B and C"


@pytest.mark.invariant
def test_the_plan_names_the_terrain_the_facts_hold_and_no_other(world, kings_row_board):
    """The map sentence names the map.terrain facts above the ordinary map, largest
    first; a board whose facts hold none for the map names none."""
    from inference import engine
    from ui.facts import model
    blue_r = kings_row_board.blue
    above = [f.value["feature"] for f in blue_r.facts.find("map.terrain", "King's Row")
             if f.value["z"] > 0][:engine.TERRAIN_NAMED]
    assert above and above[0] == "chokes"
    assert set(engine.TERRAIN_GROUND) == set(model.TERRAIN_FEATURES)
    sentence = "The wiki's article stresses %s." % engine._and(
        engine.TERRAIN_GROUND[f] for f in above)
    assert sentence in kings_row_board.plan.split("\n")[0]
    # these facts are King's Row's: another map's plan reads none of them
    assert "stresses" not in engine._plan(world, world.map("Ilios"), "", [], [], blue_r)


@pytest.mark.invariant
def test_the_plan_names_the_stages_the_facts_hold_and_no_other(world, kings_row_board):
    """One sentence names the stages with a map.stage_terrain fact, in play order,
    STAGES_NAMED at most, each by the features its fact holds; no fact, no sentence."""
    import copy

    from inference import engine
    blue_r = kings_row_board.blue
    held = blue_r.facts.find("map.stage_terrain", "King's Row")
    assert [f.value["stage"] for f in held] == ["Assault", "Escort"]
    named = [engine._and(engine.TERRAIN_GROUND[x["feature"]] for x in f.value["features"])
             for f in held]
    sentence = "Assault has the %s; Escort the %s." % tuple(named)
    assert sentence in kings_row_board.plan.split("\n")[0]

    def plan(name):
        r = copy.copy(blue_r)
        r.facts = board_facts.generate(world, Draft(name))
        return engine._plan(world, world.map(name), "", [], [], r).split("\n")[0]
    assert "Well has the environmental hazards." in plan("Ilios")
    assert "Lighthouse" not in plan("Ilios") and "Ruins" not in plan("Ilios")
    # three stages at most: the largest, told in play order
    suravasa = world.map("Suravasa")
    r = copy.copy(blue_r)
    r.facts = board_facts.generate(world, Draft("Suravasa"))
    assert not r.facts.find("map.stage_terrain")
    for stage, z in zip(suravasa.stages[:4], (1.0, 4.0, 3.0, 2.0), strict=True):
        r.facts.add("map", "Suravasa", "map.stage_terrain", stage, source="stage_terrain",
                    value={"stage": stage, "features": [{"feature": "cover", "z": z}]})
    assert engine.STAGES_NAMED == 3 and "%s has the cover; %s the cover; %s the cover." % tuple(
        suravasa.stages[1:4]) in engine._plan(world, suravasa, "", [], [], r)
    assert suravasa.stages[0] not in engine._plan(world, suravasa, "", [], [], r)
    # no stage fact: Oasis has stages and no text of theirs, Dorado no stages
    for name in ("Oasis", "Dorado", "Colosseo"):
        assert not board_facts.generate(world, Draft(name)).find("map.stage_terrain")
        assert " has the " not in plan(name), name
        assert not any(stage in plan(name) for stage in world.map(name).stages), name


@pytest.mark.invariant
def test_the_plan_says_nothing_the_board_contradicts(world):
    """A mirror is told as one, a six solved before red reveals a pick names the
    likely six it counters, "Above all" leaves out the shape every six pays and
    a rule named for another style, and the family follows the style tags."""
    from types import SimpleNamespace as Ns

    from inference import engine
    from inference.scoring import Contribution
    m = copy.copy(world.map("King's Row"))
    m.styles = {"brawl": (1.0, None), "dive": (-0.5, None), "poke": (0.0, None)}   # a brawl map
    rules = [Ns(id="two-supports-hold", name="Two supports hold a six", kind="constraint",
                category="shape", when=None, pending=False),
             Ns(id="dive-the-pocket", name="Dive the pocket", kind="constraint",
                category="matchup", when=Expr("enemy.dmg_amp >= 2"), pending=False),
             Ns(id="brawl-maps", name="Brawl maps reward durability", kind="heuristic",
                category="map", when=Expr("map.style_top == 'brawl'"), pending=False),
             Ns(id="poke-needs-reach", name="Poke needs reach", kind="heuristic",
                category="shape", when=Expr("team.style_lean == 'poke'"), pending=False),
             Ns(id="unmet", name="An unmet need", kind="heuristic", category="general",
                when=None, pending=False)]
    terms: list[Contribution] = [
        {"id": r.id, "kind": r.kind, "form": "scored" if r.kind == "constraint" else "heuristic",
         "applies": True, "weighted": 2.0, "metric": None} for r in rules[:4]]
    terms.append({"id": "unmet", "kind": "heuristic", "form": "heuristic", "applies": True,
                  "weighted": -0.5, "metric": None, "need": True})
    red_h = [world.hero("Reinhardt"), world.hero("Zarya")]
    theirs = team_metrics(world, red_h, m, [])
    red_lean = theirs["style_lean"] or theirs["style_top"]
    assert red_lean == "brawl"
    # a real Result, not a stand-in: _plan reads .facts, which Result defines
    six = engine.Result(kind="infer", map_name=m.name, red=["Reinhardt", "Zarya"], blue=[],
                        locked=[], catalog=rules, playstyle="brawl", contributions=terms)
    plan = engine._plan(world, m, "", [], red_h, six)                   # a mirror
    assert "(Reinhardt, Zarya) lean brawl too: %s." % engine.SAME_LEAN["brawl"] in plan
    assert engine.THEIR_LEAN["brawl"] not in plan
    assert "Above all: brawl maps reward durability." in plan
    six.playstyle = "poke"
    plan = engine._plan(world, m, "", [], red_h, six)
    assert "lean brawl: %s." % engine.THEIR_LEAN["brawl"] in plan
    assert "but against this red the six leans poke" in plan
    assert "Above all: brawl maps reward durability; poke needs reach." in plan
    plan = engine._plan(world, m, "", [], [], six)                      # red has revealed nothing
    assert "this red" not in plan and "but the six leans poke" in plan
    assert "No red pick yet: the six counters their likely six (Reinhardt, Zarya)." in plan
    tanks = engine._family(world, m, "brawl", "tank", ["Zarya"])
    tagged = [h for h in world.heroes.values()
              if h.role == "tank" and "brawl" in h.styles and h.released and h.name != "Zarya"]
    assert set(tanks) <= {h.name for h in tagged} and "Reinhardt" in tanks
    assert len(tanks) == min(engine.FAMILY_SIZE, len(tagged))
    assert "Zarya" not in tanks and "Sigma" not in tanks             # banned; not tagged brawl
    # fewest tags first, then the best win rate here
    keys = [(len(world.hero(n).styles), -(world.hero(n).map_win(m.id) or world.hero(n).win or 0.0))
            for n in tanks]
    assert keys == sorted(keys)
    alone = [h for h in tagged if h.styles == {"brawl"}]
    assert [world.hero(n) for n in tanks[:len(alone)]] == sorted(
        alone, key=lambda h: -(h.map_win(m.id) or h.win or 0.0))[:engine.FAMILY_SIZE]
    assert "Tanks: %s." % ", ".join(engine._family(world, m, "poke", "tank", [])) in plan


def test_the_rendered_breakdown_marks_a_need():
    """A need reads at or below zero by design, so the breakdown says which
    terms are needs; the flag rides to_dict() on each contribution."""
    from inference import engine
    r = engine.Result(kind="evaluate", map_name=None, red=[], blue=[], locked=[], catalog=[],
                      contributions=[
                          {"id": "a-reward", "kind": "heuristic", "form": "heuristic",
                           "applies": True, "weighted": 0.25, "metric": None, "need": False},
                          {"id": "a-need", "kind": "heuristic", "form": "heuristic",
                           "applies": True, "weighted": -0.11, "metric": None, "need": True}])
    assert "breakdown: a-reward +0.25 · a-need -0.11 (need)" in r.rendered()
    assert [c["need"] for c in r.to_dict()["contributions"]] == [False, True]


@pytest.mark.invariant
def test_a_metric_printed_inside_another_fact_cites_that_fact(world):
    """team.range_max rides the range_median line and team.cleanse the invuln
    line; a rule on either cites that fact, not its guard's."""
    from inference import engine
    six = ["Reinhardt", "Sigma", "Ashe", "Cassidy", "Ana", "Kiriko"]
    fs = board_facts.generate(world, Draft("King's Row", ("Zarya",), tuple(six), side="attack"))
    for metric, line in (("team.range_max", "team.range_median"), ("team.melee", "team.hitscan"),
                         ("team.cleanse", "team.invuln"), ("team.dps_count", "team.dps_floor"),
                         ("matchup.exposure_share", "matchup.coverage_share")):
        fact = engine._cited_fact(fs, [metric, "team.style_top"])
        assert fact is not None and fact.key == line, metric


@pytest.mark.invariant
def test_an_announced_hero_is_described_but_never_picked(world):
    from inference import engine
    early = [h for h in world.heroes.values() if not h.released]
    if not early:
        pytest.skip("no announced hero in the database")
    h = early[0]
    fs = board_facts.generate(world, Draft(blue=(h.name,)))       # the facts may describe it
    assert fs.find("hero.announced", h.name)
    with pytest.raises(Refusal, match="announced, not yet playable"):
        engine.infer(world, Draft(blue=(h.name,)))                    # a pick may not
    with pytest.raises(Refusal, match="announced"):
        engine.board(world, Draft(red=(h.name,)))
    r = engine.infer(world, Draft())
    assert h.name not in r.blue and all(a["blue"] for a in r.alternatives)
    assert not any(h.name in a["blue"] for a in r.alternatives)   # nor does the field hold it
    # and under a playbook that ties most sixes, where the local search swaps freely:
    # the announced hero reached the alternatives through refine once
    limit_only = [s for s in catalog.load(FIXTURE_PLAYBOOK) if s.form == "limit" and not s.soft]
    r = engine.infer(world, Draft(), catalog=limit_only)
    assert h.name not in r.blue and not any(h.name in a["blue"] for a in r.alternatives)


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
    ilios.styles = {"poke": (1.0, None), "dive": (0.2, None), "brawl": (1.0, None)}
    try:
        assert ilios.style_top == "brawl" and ilios.style_margin == 0
    finally:
        ilios.styles = derived
    once = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",)))
    twice = engine.infer(world, Draft("King's Row", ("Zarya", "Pharah"), ("Ana",)))
    assert once.blue == twice.blue and abs(once.score - twice.score) < 1e-12


@pytest.mark.invariant
def test_the_board_splits_its_solves_across_workers_and_agrees_with_one_process(world, monkeypatch):
    """Every search is cut into slices across the pool and merged here; the
    answer is byte-for-byte the sequential one, the board's weight overrides
    included (a worker loads the playbook from its files)."""
    from inference import engine
    if not engine.parallel_available():
        pytest.skip("one core, or COUNTRIX_PARALLEL=0")
    assert engine.warm() == engine.worker_count() >= 6
    weights = {h.id: 10.0 if h.weight < 10 else 0.5
               for h in catalog.load() if h.kind == "heuristic"}
    draft = Draft("King's Row", ("Zarya", "Pharah"), ("Ana", "Reinhardt"), side="attack")
    split = engine.board(world, draft, weights=weights)
    assert split.blue.to_dict()["weights"] == weights         # the override reached the worker
    monkeypatch.setenv("COUNTRIX_PARALLEL", "0")
    assert not engine.parallel_available()
    straight = engine.board(world, draft, weights=weights)

    def timeless(b):
        d = b.to_dict()
        for key in ("blue", "red", "current", "red_current", "fill", "countered"):
            if d.get(key):
                d[key].pop("seconds", None)
        return d
    assert timeless(split) == timeless(straight)
    first_line = lambda b: b.rendered().split("\n")[0]   # noqa: E731
    assert first_line(split) == first_line(straight)
    assert engine.parallel_available(catalog=[]) is False   # a caller's catalog stays in-process


def test_countrix_workers_sets_the_worker_count(monkeypatch):
    # read when the pool starts, so no pool is spawned to read it here
    from inference import engine
    monkeypatch.setenv("COUNTRIX_WORKERS", "3")
    assert engine.worker_count() == 3
    for cores, count in ((16, engine.WORKER_CEILING), (2, 6)):
        monkeypatch.setattr(engine.os, "cpu_count", lambda cores=cores: cores)
        for junk in ("0", "x"):
            monkeypatch.setenv("COUNTRIX_WORKERS", junk)
            assert engine.worker_count() == count, (cores, junk)
        monkeypatch.delenv("COUNTRIX_WORKERS")
        assert engine.worker_count() == count, cores


def test_countrix_parallel_off_keeps_the_board_in_one_process(monkeypatch):
    # read on every board: the switch holds from the next call
    from inference import engine
    monkeypatch.setattr(engine.os, "cpu_count", lambda: 4)
    monkeypatch.setenv("COUNTRIX_PARALLEL", "1")
    assert engine.parallel_available() is True
    for off in ("0", "no", "False"):
        monkeypatch.setenv("COUNTRIX_PARALLEL", off)
        assert engine.parallel_available() is False, off


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
    assert all(not c["applies"] and c["weighted"] == 0
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
        paired.synergies = {frozenset((a.id, b.id)): (1.0, "scratch")}
        paired.partners = {a.id: {b.id: (1.0, "scratch")}, b.id: {a.id: (1.0, "scratch")}}
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
def test_the_fill_is_the_optimal_whenever_the_optimal_holds_every_lock(world):
    """Locking a hero of the optimal six leaves the optimal six the best one
    that keeps the lock, so the fill must find it again. Under the shipped
    playbook every six scores zero and only the tie-break tells them apart: a
    search that moved on score alone stood still there, and locking Reinhardt
    on King's Row came back with Mizuki for Juno."""
    from inference import engine
    shipped = catalog.load()
    for map_name in ("King's Row", "Ilios"):
        best = engine.infer(world, Draft(map_name), catalog=shipped)
        for hero in best.blue:
            fill = engine.infer(world, Draft(map_name, blue=(hero,)), catalog=shipped)
            assert fill.blue == best.blue, (map_name, hero, fill.blue)


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
    absent = [h.name for h in world.heroes.values()
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
def test_one_hero_cannot_hold_two_seats(world):
    """A six with a hero twice is a five, and team_metrics would count it twice."""
    import pytest as _pytest
    for kwargs in ({"blue": ["Ana", "Ana"]}, {"red": ["Zarya", "Zarya"]},
                   {"bans": ["Sombra", "Sombra"]}):
        with _pytest.raises(Refusal, match="same hero twice"):
            world.resolve("King's Row", kwargs.get("red", []), kwargs.get("blue", []),
                          kwargs.get("bans", []))
    # but a hero may play for both teams
    world.resolve("King's Row", ["Zarya"], ["Zarya"], [])


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
