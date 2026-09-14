"""The inference layer: the expression language and catalog are pure; the
solver and evaluation run against the built database."""

import pytest

from inference import catalog, expr
from inference.expr import Expr, ExprError
from ui.facts import compute

# --- the expression language (pure) --------------------------------------

def test_expressions_read_dotted_names_and_arithmetic():
    ns = {"team": {"tanks": 1, "hitscan": 3}, "params": {"X": 2}}
    assert Expr("team.tanks == 1 and team.hitscan >= params.X").eval(ns) is True
    assert Expr("min(team.hitscan, 2) * 1.5").eval(ns) == 3.0
    assert Expr("team.missing + 1").eval(ns) == 1          # unknown reads 0
    assert Expr("'dive' if team.tanks else 'brawl'").eval(ns) == "dive"
    assert Expr("team.tanks / 0").eval(ns) == 0.0


def test_expressions_refuse_anything_beyond_the_whitelist():
    for bad in ("__import__('os')", "team.__class__", "[x for x in y]",
                "lambda: 1", "open('f')", "team.tanks = 2"):
        with pytest.raises(ExprError):
            Expr(bad).eval({"team": {}})


def test_expression_names_are_the_full_dotted_keys():
    assert Expr("team.tanks + enemy.flyers * params.K").names == [
        "enemy.flyers", "params.K", "team.tanks"]
    assert expr.lookup({"a": {"b": None}}, "a.b", default=7) == 7


# --- the catalog (pure) -----------------------------------------------------

def test_frontmatter_parses_scalars_lists_and_params():
    meta, body = catalog.parse_frontmatter(
        "---\nname: X\nweight: 2.5\nsoft: true\ntags: [a, b]\nparams:\n  K: 3\n---\n# X\nbody\n")
    assert meta == {"name": "X", "weight": 2.5, "soft": True, "tags": ["a", "b"],
                    "params": {"K": 3}}
    assert body == "# X\nbody"


def test_shipped_catalog_is_valid_and_references_real_metrics():
    cat = catalog.load()
    kinds = {h.kind for h in cat}
    assert kinds == set(catalog.KINDS) == {"constraint", "heuristic", "assumption"}
    forms = {h.form for h in cat}
    assert forms == {"limit", "scored", "heuristic", "assumption"}
    assert all(h.form == "heuristic" for h in cat if h.kind == "heuristic")
    assert any(h.form == "limit" for h in cat)         # open-queue-tanks
    assert any(h.form == "scored" for h in cat)        # peel, under-healed...
    assert all(h.form == "assumption" and not h.scored for h in cat if h.kind == "assumption")
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


# --- the solver against the built database ------------------------------------

@pytest.fixture(scope="module")
def world(db):
    from ui.facts import model
    w = model.load(db)
    db.rollback()
    return w


@pytest.mark.invariant
def test_infer_keeps_locked_picks_and_the_open_queue_shape(world):
    from inference import engine
    r = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"])
    assert len(r.blue) == 6 and "Ana" in r.blue
    roles = [world.hero(n).role for n in r.blue]
    assert roles.count("tank") <= 2
    assert r.considered > 100 and r.score > 0
    assert any(p["hero"] == "Ana" and p["locked"] for p in r.picks)
    # every pick cites facts the board for (map, red, the five) shows
    assert r.facts.blue == r.blue
    ids = {f.id for f in r.facts.facts}
    for p in r.picks:
        assert p["evidence"] and set(p["evidence"]) <= ids
    # coverage of both enemies is worth 3 points, and the optimum takes them
    cov = next(c for c in r.contributions if c["id"] == "coverage")
    assert cov["raw"] == 1.0 and cov.get("fact")


@pytest.mark.invariant
def test_infer_honours_a_hitscan_answer_to_a_flier(world):
    from inference import engine
    r = engine.infer(world, "Havana", ["Pharah", "Mercy"], [])
    assert any(world.hero(n).hitscan for n in r.blue)
    anti = next(c for c in r.contributions if c["id"] == "anti-air")
    assert anti["applies"] and anti["ok"]


@pytest.mark.invariant
def test_evaluate_ranks_a_full_five_against_the_field(world):
    from inference import engine
    r = engine.evaluate(world, "King's Row", ["Zarya", "Pharah"],
                        ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"])
    assert r.rank >= 1 and r.kind == "evaluate" and len(r.picks) == 6
    with pytest.raises(ValueError, match="exactly 6"):
        engine.evaluate(world, None, [], ["Ana"])


@pytest.mark.invariant
def test_the_tank_limit_is_the_only_shape_constraint(world, tmp_path):
    import os
    import shutil

    from inference import engine
    # two tanks is allowed by default; a third is not
    r = engine.infer(world, "King's Row", ["Zarya"], ["Winston", "D.Va"], pool_size=4)
    assert {"Winston", "D.Va"} <= set(r.blue)
    with pytest.raises(ValueError, match="no composition satisfies"):
        engine.infer(world, "King's Row", [], ["Winston", "D.Va", "Reinhardt"], pool_size=4)
    # a stricter authored constraint narrows the search the same way
    for name in os.listdir(catalog.STRATEGIES_DIR):
        if name != "open-queue-tanks.md":
            shutil.copy(os.path.join(catalog.STRATEGIES_DIR, name), tmp_path / name)
    (tmp_path / "shape.md").write_text(
        "---\nname: role queue\nkind: constraint\nrequire: team.tanks == 2 and"
        " team.damage == 2 and team.supports == 2\n---\nx\n", "utf-8")
    cat = catalog.load(str(tmp_path))
    r = engine.infer(world, "King's Row", ["Zarya"], ["Ana"], pool_size=4, catalog=cat)
    roles = sorted(world.hero(n).role for n in r.blue)
    assert roles == ["damage", "damage", "support", "support", "tank", "tank"]


@pytest.mark.invariant
def test_infer_never_drafts_a_banned_hero(world):
    from inference import engine
    r = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"],
                     bans=["Widowmaker", "Bastion", "Reinhardt"])
    assert not {"Widowmaker", "Bastion", "Reinhardt"} & set(r.blue)
    assert r.bans == ["Widowmaker", "Bastion", "Reinhardt"] and "banned" in r.rendered()
    assert r.facts.bans == r.bans
    with pytest.raises(ValueError, match="banned this match"):
        engine.infer(world, None, ["Zarya"], ["Ana"], bans=["Zarya"])


@pytest.mark.invariant
def test_board_solves_both_seats_on_opposite_sides_and_scores_the_current(world):
    from inference import engine
    b = engine.board(world, "King's Row", ["Zarya", "Pharah"], ["Ana"], side="attack")
    blue, red, cur = b["blue"], b["red"], b["current"]
    assert blue.seat == "blue" and blue.side == "attack" and blue.locked == []
    absolute = engine.infer(world, "King's Row", ["Zarya", "Pharah"], [], side="attack")
    assert blue.blue == absolute.blue                     # blue's optimal ignores your picks
    assert red.seat == "red" and red.side == "defense" and len(red.blue) == 6
    # red's optimal: their best counter to ours
    assert red.locked == [] and red.red == ["Ana"]
    theirs = engine.infer(world, "King's Row", ["Ana"], [], side="defense", seat="red")
    assert red.blue == theirs.blue
    assert cur.kind == "current" and cur.partial and cur.blue == ["Ana"]
    assert cur.contributions and cur.score is not None
    rc = b["red_current"]                                  # their comp as revealed, scored vs ours
    assert rc.seat == "red"
    assert set(rc.blue) == {"Zarya", "Pharah"}
    assert rc.red == ["Ana"]
    assert rc.partial
    assert 0 <= rc.to_dict()["normalized"] <= 100
    assert b["countered"] is not None and b["countered"].kind == "countered"
    fill = b["fill"]                                       # the empty slots, filled around Ana
    assert fill.kind == "fill"
    assert fill.locked == ["Ana"]
    assert len(fill.blue) == 6
    assert "Ana" in fill.blue
    assert [p["locked"] for p in fill.picks].count(True) == 1
    assert 0 < fill.to_dict()["normalized"] <= 100
    around = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"], side="attack")
    assert fill.blue == around.blue
    mo = b["momentum"]
    assert set(mo) >= {"blue", "red", "countered", "verdict", "partial"} and mo["partial"]
    assert mo["blue"] == cur.to_dict()["normalized"] and mo["red"] == rc.to_dict()["normalized"]
    assert ("ahead by" in mo["verdict"] or mo["verdict"].startswith("even"))
    assert "best counter" in mo["verdict"]
    # prose: the ground, what to play, them, the family
    plan = b["plan"]
    assert plan.startswith("King's Row is a Hybrid map: a capture point and then the payload path")
    assert "The archetypal brawl map; streets phase is one long corridor." in plan
    assert "You are attacking: you have to break their hold" in plan
    assert "The map rewards brawl" in plan
    assert "Their 2 picks so far (Zarya, Pharah)" in plan and "answer" in plan
    assert "If you stray from the six, stay in its family. Tanks: " in plan
    assert "Above all: " in plan
    assert plan.endswith("Based on: the rates and counters, the map, the side,"
                         " red's 2 revealed picks.")
    assert "Held to" not in plan and "D - " not in plan
    d = engine.board_dict(b)
    assert d["side"] == "attack" and d["red"]["seat"] == "red" and d["current"]["partial"]
    assert d["red_current"]["seat"] == "red"
    assert d["momentum"]["verdict"] == mo["verdict"]
    assert d["plan"] == plan
    assert d["fill"]["kind"] == "fill" and "the rest filled" in engine.board_rendered(b)
    assert "current comp" in engine.board_rendered(b) and "momentum:" in engine.board_rendered(b)
    # the side constraints fire on the right seat
    ids = {c["id"] for c in blue.contributions if c.get("applies")}
    assert "attack-breaks-the-hold" in ids and "defense-holds-the-ground" not in ids
    ids = {c["id"] for c in red.contributions if c.get("applies")}
    assert "defense-holds-the-ground" in ids


@pytest.mark.invariant
def test_a_playbook_that_scores_nothing_reads_unscored(world, monkeypatch):
    """Hard limits and prose alone tie every legal six at zero: the results
    carry no share of a best, say so, and the verdict is the one line."""
    from inference import engine
    shipped = catalog.load()
    assert catalog.scores(shipped)
    limit_only = [h for h in shipped if h.form == "limit" and not h.soft]
    assert limit_only and not catalog.scores(limit_only)
    monkeypatch.setattr(engine, "parallel_available", lambda catalog=None: False)
    b = engine.board(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"],
                     catalog=limit_only)
    d = engine.board_dict(b)
    for key in ("blue", "red", "current", "red_current", "fill", "countered"):
        assert d[key]["scoring"] is False and d[key]["normalized"] is None
        assert all(a["normalized"] is None for a in d[key]["alternatives"])
    assert d["momentum"]["verdict"].startswith("unscored") and d["momentum"]["blue"] is None
    assert "(unscored)" in b["current"].rendered() and "UNSCORED:" in b["current"].rendered()
    scored = engine.board_dict(engine.board(world, "King's Row", ["Zarya", "Pharah"],
                                            ["Ana", "Reinhardt"], catalog=shipped))
    assert scored["current"]["scoring"] is True and 0 < scored["current"]["normalized"] < 100


def test_legal_shapes_follow_the_playbook_and_the_board_carries_them(world):
    """The roster enforces what the shape limits allow: the two-tank limit
    means no triple the solver would search seats a third tank, and the
    board says so in a form the script can read."""
    from inference import engine
    from inference.solver import legal_shapes
    cat = catalog.load()
    shapes = legal_shapes(cat)
    assert shapes and all(t + d + s == 6 for t, d, s in shapes)
    assert (2, 2, 2) in shapes and all(t <= 2 for t, _, _ in shapes)
    assert (3, 2, 1) not in shapes
    seated = legal_shapes(cat, {"tank": 2, "damage": 3, "support": 0})
    assert seated and all(t == 2 and d >= 3 for t, d, _ in seated)
    b = engine.board(world, "King's Row", ["Zarya"], ["Ana"], catalog=cat)
    assert b["shapes"] == [list(s) for s in shapes]
    assert engine.board_dict(b)["shapes"] == b["shapes"]


def test_board_ranks_a_full_six_and_ignores_sides_on_control(world):
    from inference import engine
    six = ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"]
    b = engine.board(world, "Ilios", ["Pharah"], six, side="attack")
    assert b["side"] == "" and b["blue"].side == "" and b["red"].side == ""
    assert b["current"].kind == "evaluate" and b["current"].rank >= 1
    assert set(b["current"].blue) == set(six)
    assert b["blue"].locked == [] and b["blue"].to_dict()["normalized"] == 100
    assert 0 <= b["current"].to_dict()["normalized"] <= 100      # against the absolute optimal
    b = engine.board(world, None, [], [])
    assert not b["current"].blue and b["current"].partial
    # nothing locked: the optimal is the fill
    assert b["countered"] is None and b["fill"] is None
    assert b["momentum"]["verdict"] == "no picks yet on either side"
    assert b["momentum"]["blue"] is None and b["momentum"]["red"] is None
    assert b["plan"].startswith("No map yet, so this is the meta's best six")
    assert b["plan"].endswith("Based on: the rates and counters.")
    assert len(b["blue"].blue) == 6                      # the meta's best six, before any map
    b = engine.board(world, "Ilios", [], [], bans=["Widowmaker"])
    assert b["plan"].endswith("the map, 1 ban.") and b["plan"].count("\n") >= 2
    assert b["plan"].startswith("Ilios is a Control map: one point in three arenas")
    assert "Ledges and open points reward mobility; well punishes immobile comps." in b["plan"]


@pytest.mark.invariant
def test_scores_share_one_scale_per_board(world):
    # infer, evaluate and the current comp normalise against the same
    # seeded reference sample, so the same six scores the same everywhere
    from inference import engine
    r = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"])
    e = engine.evaluate(world, "King's Row", ["Zarya", "Pharah"], r.blue)
    assert abs(r.score - e.score) < 1e-9 and e.rank == 1
    assert r.to_dict()["normalized"] == 100 and e.to_dict()["normalized"] == 100
    assert all(0 <= a["normalized"] <= 100 for a in r.alternatives)
    assert r.alternatives[0]["score"] < r.score        # below the optimum, if only by a hair
    assert r.alternatives[0]["normalized"] <= 100
    best = engine.infer(world, "King's Row", ["Zarya", "Pharah"], [])
    b = engine.board(world, "King's Row", ["Zarya", "Pharah"], best.blue)
    assert abs(b["current"].score - best.score) < 1e-9 and b["blue"].blue == best.blue
    assert b["current"].to_dict()["normalized"] == 100 and b["red"].to_dict()["normalized"] == 100
    b = engine.board(world, "King's Row", ["Zarya", "Pharah"], r.blue)     # a six around Ana
    assert b["blue"].blue == best.blue and b["current"].to_dict()["normalized"] <= 100
    again = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"], pool_size=4)
    assert abs(again.score - engine.evaluate(
        world, "King's Row", ["Zarya", "Pharah"], again.blue).score) < 1e-9


def test_a_constraint_is_a_limit_or_scored_or_prose_never_a_heuristic(tmp_path):
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
                "---\nname: b\nkind: constraint\nprose: true\n---\nx\n",
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
    assert Expr("team.tanks ** 2").eval({"team": {"tanks": 3}}) == 9
    assert Expr("team.style_lean == 'dive'").eval({"team": {"style_lean": "dive"}}) is True


def test_the_momentum_verdict_reads_the_two_current_comps():
    from inference import engine
    class R:
        def __init__(self, blue, score, best, partial=False):
            self.blue, self.score, self.best, self.partial = blue, score, best, partial
    even = engine._momentum(R(["a"], 8, 10), R(["b"], 7.8, 10), None)
    assert even["verdict"].startswith("even") and even["blue"] == 80 and even["red"] == 78
    blue = engine._momentum(R(["a"] * 6, 9, 10), R(["b"] * 6, 5, 10), R(["a"] * 6, 3, 10))
    assert blue["verdict"].startswith("blue ahead by 40") and blue["countered"] == 30
    assert "your picks hold 30 / 100" in blue["verdict"] and not blue["partial"]
    red = engine._momentum(R(["a"], 2, 10, partial=True), R(["b"] * 6, 9, 10), None)
    assert red["verdict"].startswith("red ahead by 70") and "(partial picks)" in red["verdict"]
    only_red = engine._momentum(R([], 0, 10), R(["b"], 5, 10), None)
    assert only_red["verdict"].startswith("red has revealed")


def test_the_plan_reads_every_authored_map_note(world):
    from inference import engine
    for m in world.maps.values():                         # each note is a sentence of the plan
        note = m.styles.get(m.style_top, (None, None))[1] if m.style_top else None
        if note:
            plan = engine.board(world, m.name, [], [])["plan"]
            assert engine._sentence(note) in plan, m.name
    assert engine._and(["A"]) == "A" and engine._and(["A", "B", "C"]) == "A, B and C"
    names = engine._hero_names(world, "winston d.va wrecking ball nobody")
    assert names == ["Winston", "D.Va", "Wrecking Ball"]


def test_an_announced_hero_is_described_but_never_picked(world):
    from inference import engine
    from ui.facts import engine as facts_engine
    early = [h for h in world.heroes.values() if not h.released]
    if not early:
        pytest.skip("no announced hero in the database")
    h = early[0]
    fs = facts_engine.generate(world, None, [], [h.name])          # the facts may describe it
    assert fs.find("hero.announced", h.name)
    with pytest.raises(ValueError, match="announced, not yet playable"):
        engine.infer(world, None, [], [h.name])                    # a pick may not
    with pytest.raises(ValueError, match="announced"):
        engine.board(world, None, [h.name], [])
    # the default pool: a pool of 8 with no locks needs more than the container's 1 GiB
    r = engine.infer(world, None, [], [])
    assert h.name not in r.blue and all(a["blue"] for a in r.alternatives)
    assert not any(h.name in a["blue"] for a in r.alternatives)   # nor does the field hold it


@pytest.mark.invariant
def test_style_ties_break_by_name_so_hash_order_cannot_reach_the_answer(world):
    """A set of style names iterates in an order that changes with the process's
    hash seed; the tie-breaks must not depend on it - two views of the same
    heroes whose style sets iterate in opposite orders agree on every metric,
    and the same board solves to the same six twice in a row."""
    from inference import engine
    heroes = [world.hero(n) for n in ("Reinhardt", "Zarya", "Widowmaker", "Ana", "Lúcio", "Mercy")]
    forward = compute.team_metrics(world, heroes, world.map("Ilios"), [])

    from ui.facts import model

    class Reversed(model.Hero):                # the same hero, its styles iterated backwards
        def __init__(self, hero):
            self.__dict__ = dict(hero.__dict__)
            self.styles = sorted(hero.styles, reverse=True)   # the other iteration order
    backward = compute.team_metrics(world, [Reversed(h) for h in heroes], world.map("Ilios"), [])
    for key in ("style_top", "style_lean", "style_counts", "style_fit"):
        assert forward[key] == backward[key], key
    ilios = world.map("Ilios")
    tied = dict(ilios.styles)
    ilios.styles = dict(reversed(list(tied.items())))
    try:
        assert ilios.style_top == max(sorted(tied), key=lambda st: (tied[st][0] or 0, st))
    finally:
        ilios.styles = tied
    once = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"])
    twice = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"])
    assert once.blue == twice.blue and abs(once.score - twice.score) < 1e-12


@pytest.mark.invariant
def test_the_board_splits_its_solves_across_workers_and_agrees_with_one_process(world, monkeypatch):
    """Blue's optimal and red's counter run in two workers, the fill in the
    parent; the answer is byte-for-byte the sequential one."""
    from inference import engine
    if not engine.parallel_available():
        pytest.skip("one core, or COUNTER_MATRIX_PARALLEL=0")
    assert engine.warm() == engine.WORKERS
    split = engine.board(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"],
                         side="attack")
    assert split["blue"].catalog and not hasattr(split["blue"], "solver")   # crossed the boundary
    monkeypatch.setattr(engine, "PARALLEL", False)
    assert not engine.parallel_available()
    straight = engine.board(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"],
                            side="attack")
    assert hasattr(straight["blue"], "solver")

    def timeless(b):
        d = engine.board_dict(b)
        for key in ("blue", "red", "current", "red_current", "fill", "countered"):
            if d.get(key):
                d[key].pop("seconds", None)
        return d
    assert timeless(split) == timeless(straight)
    first_line = lambda b: engine.board_rendered(b).split("\n")[0]   # noqa: E731
    assert first_line(split) == first_line(straight)
    assert engine.parallel_available(catalog=[]) is False   # a caller's catalog stays in-process


@pytest.mark.invariant
def test_a_mirror_pick_cites_its_own_facts_not_the_enemy_copy(world):
    """Tracer on both teams: our Tracer's reasons come from our side of the
    board - never "answers Ana" (our Ana, whom red's Tracer answers) and
    never "partner of Winston" (red's Winston)."""
    from inference import engine
    r = engine.evaluate(world, "King's Row", ["Winston", "Genji", "Tracer"],
                        ["D.Va", "Reinhardt", "Tracer", "Brigitte", "Lúcio", "Ana"])
    ours = next(p for p in r.picks if p["hero"] == "Tracer")
    assert "answers Ana" not in ours["why"] and "Winston" not in ours["why"]
    clues = ("answers Genji", "answers Tracer", "partner of D.Va")
    assert any(clue in ours["why"] for clue in clues)
