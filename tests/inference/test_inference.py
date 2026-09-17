"""The inference layer: the expression language and catalog are pure; the
solver and evaluation run against the built database."""

import os
import shutil

import pytest

from inference import catalog
from inference.expr import Expr, ExprError
from tests.inference import FIXTURE_PLAYBOOK
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


# --- the catalog (pure) -----------------------------------------------------

def test_frontmatter_parses_scalars_lists_and_params():
    meta, body = catalog.parse_frontmatter(
        "---\nname: X\nweight: 2.5\nsoft: true\ntags: [a, b]\nparams:\n  K: 3\n---\n# X\nbody\n")
    assert meta == {"name": "X", "weight": 2.5, "soft": True, "tags": ["a", "b"],
                    "params": {"K": 3}}
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
def kings_row_board(world):
    """The board the tests read most - King's Row, Zarya and Pharah revealed, Ana and
    Reinhardt locked, the reference playbook - solved once per module (a caller's
    catalog keeps the solve in one process)."""
    from inference import engine
    return engine.board(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"],
                        catalog=catalog.load(FIXTURE_PLAYBOOK))


@pytest.fixture(scope="module")
def world(db):
    from ui.facts import model
    w = model.load(db)
    db.rollback()
    return w


@pytest.mark.invariant
def test_infer_keeps_locked_picks_and_the_open_queue_shape(world):
    from inference import engine
    r = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"],
                     catalog=catalog.load(FIXTURE_PLAYBOOK))
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
    r = engine.infer(world, "Havana", ["Pharah", "Mercy"], [],
                     catalog=catalog.load(FIXTURE_PLAYBOOK))
    assert any(world.hero(n).hitscan for n in r.blue)
    anti = next(c for c in r.contributions if c["id"] == "anti-air")
    assert anti["applies"] and anti["ok"]


@pytest.mark.invariant
def test_evaluate_ranks_a_full_six_against_the_field(world):
    from inference import engine
    r = engine.evaluate(world, "King's Row", ["Zarya", "Pharah"],
                        ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"])
    assert r.rank >= 1 and r.kind == "evaluate" and len(r.picks) == 6
    with pytest.raises(ValueError, match="exactly 6"):
        engine.evaluate(world, None, [], ["Ana"])


@pytest.mark.invariant
def test_shape_limits_bound_the_search_and_a_stricter_one_narrows_it(world, tmp_path):
    from inference import engine
    fix = catalog.load(FIXTURE_PLAYBOOK)
    # two tanks is allowed under the two-tank limit; a third is not
    r = engine.infer(world, "King's Row", ["Zarya"], ["Winston", "D.Va"], pool_size=4,
                     catalog=fix)
    assert {"Winston", "D.Va"} <= set(r.blue)
    with pytest.raises(ValueError, match="no composition satisfies"):
        engine.infer(world, "King's Row", [], ["Winston", "D.Va", "Reinhardt"], pool_size=4,
                     catalog=fix)
    # a stricter authored limit narrows the search the same way
    for name in os.listdir(FIXTURE_PLAYBOOK):
        if name != "open-queue-tanks.md":
            shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
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
    fix = catalog.load(FIXTURE_PLAYBOOK)        # the reference playbook has the side rules
    b = engine.board(world, "King's Row", ["Zarya", "Pharah"], ["Ana"], side="attack", catalog=fix)
    blue, red, cur = b["blue"], b["red"], b["current"]
    assert blue.seat == "blue" and blue.side == "attack" and blue.locked == []
    absolute = engine.infer(world, "King's Row", ["Zarya", "Pharah"], [], side="attack",
                            catalog=fix)
    assert blue.blue == absolute.blue                     # blue's optimal ignores your picks
    assert red.seat == "red" and red.side == "defense" and len(red.blue) == 6
    # red's optimal: their best counter to ours
    assert red.locked == [] and red.red == ["Ana"]
    theirs = engine.infer(world, "King's Row", ["Ana"], [], side="defense", seat="red",
                          catalog=fix)
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
    around = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"], side="attack",
                          catalog=fix)
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


def test_weights_override_a_heuristic_for_one_board_and_never_the_file():
    """The playbook tab's sliders: `id:value` strings or a mapping become
    weights clamped to the file's range; the catalog's heuristic carries the
    override in a copy, the loaded one and its file are untouched, and a
    constraint or an unknown id is ignored."""
    parsed = catalog.parse_weights(["a:2", "b:11", "c:-1", "nonsense", "d:x"])
    assert parsed == {"a": 2.0, "b": 10.0, "c": 0.0}
    assert catalog.parse_weights({"a": "3.5"}) == {"a": 3.5}
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
    moving = next(c["id"] for c in plain["current"].contributions
                  if c["kind"] == "heuristic" and c.get("weighted"))
    heuristic = next(h for h in fix if h.id == moving)
    weights = {heuristic.id: 10.0 if heuristic.weight < 10 else 0.5}
    tilted = engine.board(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"],
                          catalog=fix, weights=weights)
    assert tilted["current"].to_dict()["weights"][heuristic.id] == weights[heuristic.id]
    assert plain["current"].to_dict()["weights"][heuristic.id] == heuristic.weight
    assert tilted["current"].score != plain["current"].score
    assert next(h for h in catalog.load(FIXTURE_PLAYBOOK)
                if h.id == heuristic.id).weight == heuristic.weight


@pytest.mark.invariant
def test_fight_odds_pit_the_two_shares_against_each_other(world, kings_row_board):
    """Both seats scored: each side's odds are its share over the two shares'
    sum, the pair splits 100, and the verdict says so; one seat unscored or
    empty: no odds."""
    from inference import engine
    b = engine.board_dict(kings_row_board)
    mo = b["momentum"]
    n, m = mo["blue"], mo["red"]
    assert isinstance(n, int) and isinstance(m, int) and n + m > 0
    blue_odds = round(100.0 * n / (n + m))
    assert mo["odds"] == {"blue": blue_odds, "red": 100 - blue_odds}
    assert "fight odds blue %d%%, red %d%%" % (blue_odds, 100 - blue_odds) in mo["verdict"]
    alone = engine.board_dict(engine.board(world, "King's Row", ["Zarya", "Pharah"], [],
                                           catalog=catalog.load(FIXTURE_PLAYBOOK)))
    assert alone["momentum"]["blue"] is None and alone["momentum"]["odds"] is None


@pytest.mark.invariant
def test_a_playbook_that_scores_nothing_reads_unscored(world):
    """Hard limits and prose alone tie every legal six at zero: the results
    carry no share of a best, say so, and the verdict is the one line."""
    from inference import engine
    reference = catalog.load(FIXTURE_PLAYBOOK)
    assert catalog.scores(reference)
    limit_only = [h for h in reference if h.form == "limit" and not h.soft]
    assert limit_only and not catalog.scores(limit_only)
    b = engine.board(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"],
                     catalog=limit_only)
    d = engine.board_dict(b)
    for key in ("blue", "red"):                     # the optimal is the reference: 100, always
        assert d[key]["scoring"] is True and d[key]["normalized"] == 100
    for key in ("current", "red_current", "fill", "countered"):
        assert d[key]["scoring"] is False and d[key]["normalized"] is None
        assert all(a["normalized"] is None for a in d[key]["alternatives"])
    assert d["momentum"]["verdict"].startswith("unscored") and d["momentum"]["blue"] is None
    assert "(unscored)" in b["current"].rendered() and "UNSCORED:" in b["current"].rendered()
    scored = engine.board_dict(engine.board(world, "King's Row", ["Zarya", "Pharah"],
                                            ["Ana", "Reinhardt"], catalog=reference))
    assert scored["current"]["scoring"] is True and 0 < scored["current"]["normalized"] < 100
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
    assert catalog.scores(scratch)
    grounded = engine.board_dict(engine.board(world, "King's Row", ["Zarya", "Ana"],
                                              ["Reinhardt", "Cassidy"], catalog=scratch))
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
    empty = engine.board_dict(engine.board(world, None, [], [], catalog=scratch))
    assert empty["momentum"]["verdict"] == "no picks yet on either side"
    assert empty["blue"]["normalized"] == 100 and empty["blue"]["unscored"] is None
    assert empty["blue"]["red"] == empty["expected"]["blue"]           # countering the likely six
    flying = engine.board_dict(engine.board(world, "King's Row", ["Zarya", "Pharah"],
                                            ["Reinhardt", "Cassidy"], catalog=scratch))
    assert flying["blue"]["scoring"] is True and flying["blue"]["normalized"] == 100
    assert flying["current"]["unscored"] is None and flying["current"]["normalized"] is not None
    # blue fields no flier, so red's seat still waits: the verdict reads each side on its own
    assert flying["red_current"]["scoring"] is False
    verdict = flying["momentum"]["verdict"]
    assert verdict.startswith("blue %d / 100" % flying["current"]["normalized"])
    assert "red unscored: Fliers need hitscan cover waits for matchup.flyers >= 1" in verdict
    assert flying["momentum"]["blue"] == flying["current"]["normalized"]
    assert flying["momentum"]["red"] is None and flying["momentum"]["odds"] is None


@pytest.mark.invariant
def test_legal_shapes_follow_the_playbook_and_the_board_carries_them(world):
    """The roster enforces what the shape limits allow: the two-tank limit
    means no triple the solver would search seats a third tank, and the
    board says so in a form the script can read."""
    from inference import engine
    from inference.solver import legal_shapes
    cat = catalog.load(FIXTURE_PLAYBOOK)
    shapes = legal_shapes(cat)
    assert shapes and all(t + d + s == 6 for t, d, s in shapes)
    assert (2, 2, 2) in shapes and all(t <= 2 for t, _, _ in shapes)
    assert (3, 2, 1) not in shapes
    seated = legal_shapes(cat, {"tank": 2, "damage": 3, "support": 0})
    assert seated and all(t == 2 and d >= 3 for t, d, _ in seated)
    b = engine.board(world, "King's Row", ["Zarya"], ["Ana"], catalog=cat)
    assert b["shapes"] == [list(s) for s in shapes]
    d = engine.board_dict(b)
    assert d["shapes"] == b["shapes"]
    # red's likely six rides along - static: the map and the meta, not their reveal
    assert d["expected"]["kind"] == "expected" and "Zarya" not in d["expected"]["blue"]
    assert len(d["expected"]["picks"]) == 6 and all(p["why"] for p in d["expected"]["picks"])
    assert not any(p["locked"] for p in d["expected"]["picks"])


@pytest.mark.invariant
def test_blue_counters_the_likely_six_until_red_reveals_a_pick(world, monkeypatch):
    """With no red pick the board solves blue against red's likely six, so the
    opening suggestion is a counter to what the map and the meta say red
    fields; the first reveal replaces that with red's actual picks."""
    from inference import engine
    monkeypatch.setattr(engine, "parallel_available", lambda catalog=None: False)
    m = world.map("King's Row")
    likely = [p["hero"] for p in compute.expected_picks(world, m, [], [])]
    b = engine.board(world, "King's Row", [], ["Ana"])
    assert b["blue"].red == likely and b["current"].red == likely and b["fill"].red == likely
    assert b["expected"].blue == likely and b["expected"].kind == "expected"
    assert [p["hero"] for p in b["expected"].picks] == likely
    assert "their likely starting comp" in engine.board_rendered(b)
    revealed = engine.board(world, "King's Row", ["Zarya"], ["Ana"])
    assert revealed["blue"].red == ["Zarya"] and revealed["current"].red == ["Zarya"]
    assert revealed["expected"].blue == likely                      # static


@pytest.mark.invariant
def test_board_ranks_a_full_six_and_ignores_sides_on_control(world):
    from inference import engine
    fix = catalog.load(FIXTURE_PLAYBOOK)
    six = ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"]
    b = engine.board(world, "Ilios", ["Pharah"], six, side="attack", catalog=fix)
    assert b["side"] == "" and b["blue"].side == "" and b["red"].side == ""
    assert b["current"].kind == "evaluate" and b["current"].rank >= 1
    assert set(b["current"].blue) == set(six)
    assert b["blue"].locked == [] and b["blue"].to_dict()["normalized"] == 100
    assert 0 <= b["current"].to_dict()["normalized"] <= 100      # against the absolute optimal
    b = engine.board(world, None, [], [], catalog=fix)
    assert not b["current"].blue and b["current"].partial
    # nothing locked: the optimal is the fill
    assert b["countered"] is None and b["fill"] is None
    assert b["momentum"]["verdict"] == "no picks yet on either side"
    assert b["momentum"]["blue"] is None and b["momentum"]["red"] is None
    assert b["plan"].startswith("No map yet, so this is the meta's best six")
    assert b["plan"].endswith("Based on: the rates and counters.")
    assert len(b["blue"].blue) == 6                      # the meta's best six, before any map
    b = engine.board(world, "Ilios", [], [], bans=["Widowmaker"], catalog=fix)
    assert b["plan"].endswith("the map, 1 ban.") and b["plan"].count("\n") >= 2
    assert b["plan"].startswith("Ilios is a Control map: one point in three arenas")
    assert "Ledges and open points reward mobility; well punishes immobile comps." in b["plan"]


@pytest.mark.invariant
def test_scores_share_one_scale_per_board(world):
    # infer, evaluate and the current comp normalise against the same
    # seeded reference sample, so the same six scores the same everywhere
    from inference import engine
    fix = catalog.load(FIXTURE_PLAYBOOK)       # a rich playbook: alternatives fall below the best
    r = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"], catalog=fix)
    e = engine.evaluate(world, "King's Row", ["Zarya", "Pharah"], r.blue, catalog=fix)
    assert abs(r.score - e.score) < 1e-9 and e.rank == 1
    assert r.to_dict()["normalized"] == 100 and e.to_dict()["normalized"] == 100
    assert all(0 <= a["normalized"] <= 100 for a in r.alternatives)
    assert r.alternatives[0]["score"] < r.score        # below the optimum, if only by a hair
    assert r.alternatives[0]["normalized"] <= 100
    best = engine.infer(world, "King's Row", ["Zarya", "Pharah"], [], catalog=fix)
    b = engine.board(world, "King's Row", ["Zarya", "Pharah"], best.blue, catalog=fix)
    assert abs(b["current"].score - best.score) < 1e-9 and b["blue"].blue == best.blue
    assert b["current"].to_dict()["normalized"] == 100 and b["red"].to_dict()["normalized"] == 100
    b = engine.board(world, "King's Row", ["Zarya", "Pharah"], r.blue, catalog=fix)  # around Ana
    assert b["blue"].blue == best.blue and b["current"].to_dict()["normalized"] <= 100
    again = engine.infer(world, "King's Row", ["Zarya", "Pharah"], ["Ana"], pool_size=4,
                         catalog=fix)
    assert abs(again.score - engine.evaluate(
        world, "King's Row", ["Zarya", "Pharah"], again.blue, catalog=fix).score) < 1e-9


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
    assert Expr("team.tanks ** 2").eval({"team": {"tanks": 3}}) == 9
    assert Expr("team.style_lean == 'dive'").eval({"team": {"style_lean": "dive"}}) is True


def test_the_momentum_verdict_reads_the_two_current_comps():
    from inference import engine
    fix = catalog.load(FIXTURE_PLAYBOOK)

    def comp(blue, score, best, partial=False):
        r = engine.Result("current", None, [], blue, blue, fix)
        r.score, r.best, r.partial = score, best, partial
        return r
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
def test_the_plan_reads_every_authored_map_note(world, kings_row_board):
    """Every map's authored note is a sentence of its plan. One board is solved
    through the public path; the other maps' plans are composed from that
    board's optimal, since the note is the map's and the solve is not."""
    from inference import engine
    blue_r = kings_row_board["blue"]
    for m in world.maps.values():                         # each note is a sentence of the plan
        note = m.styles.get(m.style_top, (None, None))[1] if m.style_top else None
        if note:
            plan = (kings_row_board["plan"] if m.name == "King's Row"
                    else engine._plan(world, m, "", [], [], blue_r))
            assert engine._sentence(note) in plan, m.name
    assert engine._and(["A"]) == "A" and engine._and(["A", "B", "C"]) == "A, B and C"
    names = engine._hero_names(world, "winston d.va wrecking ball nobody")
    assert names == ["Winston", "D.Va", "Wrecking Ball"]


@pytest.mark.invariant
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
    r = engine.infer(world, None, [], [])
    assert h.name not in r.blue and all(a["blue"] for a in r.alternatives)
    assert not any(h.name in a["blue"] for a in r.alternatives)   # nor does the field hold it
    # and under a playbook that ties most sixes, where the local search swaps freely:
    # the announced hero reached the alternatives through refine once
    limit_only = [s for s in catalog.load(FIXTURE_PLAYBOOK) if s.form == "limit" and not s.soft]
    r = engine.infer(world, None, [], [], catalog=limit_only)
    assert h.name not in r.blue and not any(h.name in a["blue"] for a in r.alternatives)


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
    parent; the answer is byte-for-byte the sequential one, the board's
    weight overrides included (a worker loads the playbook from its files)."""
    from inference import engine
    if not engine.parallel_available():
        pytest.skip("one core, or COUNTER_MATRIX_PARALLEL=0")
    assert engine.warm() == engine.WORKERS
    weights = {h.id: 10.0 if h.weight < 10 else 0.5
               for h in catalog.load() if h.kind == "heuristic"}
    split = engine.board(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"],
                         side="attack", weights=weights)
    assert split["blue"].catalog and not hasattr(split["blue"], "solver")   # crossed the boundary
    assert split["blue"].to_dict()["weights"] == weights         # the override reached the worker
    monkeypatch.setattr(engine, "PARALLEL", False)
    assert not engine.parallel_available()
    straight = engine.board(world, "King's Row", ["Zarya", "Pharah"], ["Ana", "Reinhardt"],
                            side="attack", weights=weights)
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
