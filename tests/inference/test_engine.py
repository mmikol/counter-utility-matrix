"""board(): both seats on opposite sides, the weights it is given, the fight
odds, the shapes and the queue's tank limit, an empty catalog kept as the
caller's, the likely six, a full six on control, every seat of a board on the
synthetic World, the page's boards superseding one another, and the healing
floor on top of the default engine. Every board is the synthetic World's but
the last, King's Row on the built database. test_board_gate holds the lobby's
limits on every door."""

import pytest

from db import Refusal
from facts import compute
from facts.draft import MAX_TANKS, Draft
from facts.records import MapRate
from facts.team import team_metrics
from inference import catalog
from inference.base import DEFAULT, OFF
from inference.result import scores
from tests.inference import ASSUMPTIONS_ONLY, FIXTURE_PLAYBOOK, heal_rate


def test_board_solves_both_seats_on_opposite_sides_and_scores_the_current(synthetic_world):
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)        # the reference playbook has the side rules
    b = engine.board(world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",), side="attack"),
                     catalog=fix)
    blue, red, cur = b.blue, b.red, b.current
    assert blue.seat == "blue" and blue.side == "attack" and blue.locked == []
    absolute = engine.infer(world, Draft("Harbor Gate", ("Mortar", "Gale"), (), side="attack"),
                            catalog=fix)
    assert blue.blue == absolute.blue                     # blue's optimal ignores your picks
    assert red.seat == "red" and red.side == "defense" and len(red.blue) == 6
    # red's optimal: their best counter to ours
    assert red.locked == [] and red.red == ["Balm"]
    theirs = engine.infer(world, Draft("Harbor Gate", ("Balm",), (), side="defense"), catalog=fix)
    assert red.blue == theirs.blue
    assert cur.kind == "current" and cur.partial and cur.blue == ["Balm"]
    assert cur.contributions and cur.score is not None
    rc = b.red_current                                  # their comp as revealed, scored vs ours
    assert rc.seat == "red"
    assert set(rc.blue) == {"Mortar", "Gale"}
    assert rc.red == ["Balm"]
    assert rc.partial
    assert rc.to_dict()["normalized"] is None        # a partial team has no share
    assert b.countered is not None and b.countered.kind == "countered"
    fill = b.fill                                       # the empty slots, filled around Balm
    assert fill.kind == "fill"
    assert fill.locked == ["Balm"]
    assert len(fill.blue) == 6
    assert "Balm" in fill.blue
    assert [p["locked"] for p in fill.picks].count(True) == 1
    assert 0 < fill.to_dict()["normalized"] <= 100
    around = engine.infer(world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",),
                                       side="attack"), catalog=fix)
    assert fill.blue == around.blue
    mo = b.momentum
    assert set(mo) >= {"blue", "red", "countered", "verdict", "partial"} and mo["partial"]
    # each seat is half-drafted, so its share is read through its fill - the best
    # six reachable from its picks - not off the picks alone; both current comps'
    # dicts report no share of their own.
    assert mo["blue"] == fill.to_dict()["normalized"]
    assert mo["red"] is not None
    assert cur.to_dict()["normalized"] is None and rc.to_dict()["normalized"] is None
    assert ("ahead by" in mo["verdict"] or mo["verdict"].startswith("even"))
    assert "best counter" in mo["verdict"]
    # prose: the ground, what to play, them, the family
    plan = b.plan
    assert plan.startswith("Harbor Gate is a Hybrid map: a capture point and then the payload path")
    assert "You are attacking: you have to break their hold" in plan
    assert "The map rewards %s" % world.map("Harbor Gate").style_top in plan
    assert "Their 2 picks so far (Mortar, Gale)" in plan and "answer" in plan
    assert "If you stray from the six, stay in its family. Tanks: " in plan
    assert "Above all: " in plan
    assert plan.endswith("Based on: the Role Queue rates and counters, the map, the side,"
                         " your 1 pick, red's 2 revealed picks.")
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


def test_the_board_scores_under_the_weights_it_is_given(synthetic_world, harbor_gate_board):
    """A weight set on the board changes the score, every result says the
    weights it was scored under, and the file is untouched."""
    from inference import engine
    plain = harbor_gate_board
    fix = catalog.load(FIXTURE_PLAYBOOK)
    # a heuristic that actually moves this comp's score (one at the reference floor would not)
    moving = next(c["id"] for c in plain.current.contributions
                  if c["kind"] == "heuristic" and c.get("weighted"))
    heuristic = next(h for h in fix if h.id == moving)
    weights = {heuristic.id: 10.0 if heuristic.weight < 10 else 0.5}
    tilted = engine.board(synthetic_world,
                          Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm", "Anvil")),
                          catalog=fix, brief=engine.Brief(weights=weights))
    assert tilted.current.to_dict()["weights"][heuristic.id] == weights[heuristic.id]
    assert plain.current.to_dict()["weights"][heuristic.id] == heuristic.weight
    assert tilted.current.score != plain.current.score
    assert next(h for h in catalog.load(FIXTURE_PLAYBOOK)
                if h.id == heuristic.id).weight == heuristic.weight


def test_fight_odds_pit_the_two_shares_against_each_other(synthetic_world, harbor_gate_board):
    """Both seats scored: each side's odds are its share over the two shares'
    sum, the pair splits 100, and the verdict says so; one seat unscored or
    empty: no odds."""
    from inference import engine
    b = harbor_gate_board.to_dict()
    mo = b["momentum"]
    n, m = mo["blue"], mo["red"]
    assert isinstance(n, int) and isinstance(m, int) and n + m > 0
    blue_odds = round(100.0 * n / (n + m))
    assert mo["odds"] == {"blue": blue_odds, "red": 100 - blue_odds}
    assert "fight odds blue %d%%, red %d%%" % (blue_odds, 100 - blue_odds) in mo["verdict"]
    alone = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar", "Gale")),
                         catalog=catalog.load(FIXTURE_PLAYBOOK)).to_dict()
    assert alone["momentum"]["blue"] is None and alone["momentum"]["odds"] is None


def test_legal_shapes_follow_the_playbook_and_the_board_carries_them(synthetic_world):
    """The roster enforces what the shape limits allow: the two-tank limit
    means no triple the solver would search seats a third tank, and the
    board says so in a form the script can read."""
    from inference import engine
    from inference.shapes import Shape, legal_shapes
    cat = catalog.load(FIXTURE_PLAYBOOK)
    shapes = legal_shapes(cat)
    assert shapes and all(t + d + s == 6 for t, d, s in shapes)
    assert (2, 2, 2) in shapes and all(t <= 2 for t, _, _ in shapes)
    assert (3, 2, 1) not in shapes
    seated = legal_shapes(cat, Shape(tanks=2, damage=3, supports=0))
    assert seated and all(t == 2 and d >= 3 for t, d, _ in seated)
    b = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar",), ("Balm",)), catalog=cat)
    assert b.shapes == [list(s) for s in shapes]
    d = b.to_dict()
    assert d["shapes"] == b.shapes
    # red's likely six rides along - static: the map and the meta, not their reveal
    assert d["expected"]["kind"] == "expected" and "Mortar" not in d["expected"]["blue"]
    assert len(d["expected"]["picks"]) == 6 and all(p["why"] for p in d["expected"]["picks"])
    assert not any(p["locked"] for p in d["expected"]["picks"])


def test_the_queue_caps_tanks_at_two_whatever_the_playbook_holds(synthetic_world):
    """A playbook of assumptions alone writes no shape limit and scores
    nothing, so every six ties and the map's win rates rank the pools - tanks, once every tank
    here wins ten points more. The queue's own limit binds all the same: no
    six the board shows fields a third tank, the shapes the roster enforces
    stop at two, and a third tank is refused as the queue's."""
    from inference import engine
    world = synthetic_world
    for h in world.heroes.values():
        if h.role == "tank":
            h.win += 10
            h.map_rates = {mid: MapRate(r.win + 10, r.pick) for mid, r in h.map_rates.items()}
    assert not any(h.form == "limit" for h in ASSUMPTIONS_ONLY)      # the cap is the engine's
    for map_name, blue in (("Harbor Gate", []), ("Ember Ruins", []),
                           ("Harbor Gate", ["Anvil", "Kite"])):
        d = engine.board(world, Draft(map_name, (), tuple(blue)),
                         catalog=ASSUMPTIONS_ONLY).to_dict()
        sixes = [d[seat]["blue"] for seat in ("blue", "red", "fill", "expected") if d[seat]]
        assert len(sixes) == (4 if blue else 3)
        for six in sixes:
            assert sum(world.hero(n).role == "tank" for n in six) <= MAX_TANKS, (map_name, six)
        assert max(t for t, _, _ in d["shapes"]) == MAX_TANKS
    for blue in (["Anvil", "Kite", "Mortar"], ["Anvil", "Kite", "Mortar", "Balm"]):
        with pytest.raises(Refusal, match="the queue allows at most 2 tanks"):
            engine.board(world, Draft("Harbor Gate", (), tuple(blue)),
                         catalog=ASSUMPTIONS_ONLY)
    with pytest.raises(Refusal, match="the queue allows at most 2 tanks"):
        engine.evaluate(world, Draft("Harbor Gate", (),
                                     ("Anvil", "Kite", "Mortar", "Balm", "Tansy", "Needle")),
                        catalog=ASSUMPTIONS_ONLY)


def test_an_empty_catalog_is_the_callers_and_loads_no_playbook(synthetic_world, monkeypatch):
    """Only a catalog left out is the playbook in force: [] is the caller's
    own, as parallel.available already reads it, and scores nothing."""
    from inference import engine

    def load(directory=None):
        raise AssertionError("the playbook was loaded")
    monkeypatch.setattr(engine.catalog_module, "load", load)
    result = engine.infer(synthetic_world, Draft("Harbor Gate"), catalog=[], top=1)
    assert len(result.blue) == 6 and result.catalog == []
    b = engine.board(synthetic_world, Draft("Harbor Gate"), catalog=[])
    assert len(b.blue.blue) == 6 and b.blue.catalog == []


def test_blue_counters_the_likely_six_until_red_reveals_a_pick(synthetic_world):
    """With no red pick the board solves blue against red's likely six, so the
    opening suggestion is a counter to what the map and the meta say red
    fields; the first reveal replaces that with red's actual picks."""
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)
    m = world.map("Harbor Gate")
    likely = [p["hero"] for p in compute.expected_picks(world, m)]
    b = engine.board(world, Draft("Harbor Gate", (), ("Balm",)), catalog=fix)
    assert b.blue.red == likely and b.current.red == likely and b.fill.red == likely
    assert b.expected.blue == likely and b.expected.kind == "expected"
    assert [p["hero"] for p in b.expected.picks] == likely
    assert "their likely starting comp" in b.rendered()
    revealed = engine.board(world, Draft("Harbor Gate", ("Mortar",), ("Balm",)), catalog=fix)
    assert revealed.blue.red == ["Mortar"] and revealed.current.red == ["Mortar"]
    assert revealed.expected.blue == likely                      # static


def test_board_ranks_a_full_six_and_ignores_sides_on_control(synthetic_world):
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)
    six = ["Anvil", "Mortar", "Rook", "Needle", "Balm", "Tansy"]
    b = engine.board(world, Draft("Ember Ruins", ("Gale",), tuple(six), side="attack"),
                     catalog=fix)
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
    assert b.plan.endswith("Based on: the Role Queue rates and counters.")
    assert len(b.blue.blue) == 6                      # the meta's best six, before any map
    b = engine.board(world, Draft("Ember Ruins", (), (), ("Needle",)), catalog=fix)
    assert b.plan.endswith("the map, 1 ban.") and b.plan.count("\n") >= 2
    assert b.plan.startswith("Ember Ruins is a Control map: one point in three arenas")
    assert "The map rewards %s" % world.map("Ember Ruins").style_top in b.plan


def test_a_board_on_the_synthetic_world_holds_every_seat(synthetic_world, scratch_playbook):
    """With red revealed and one blue pick locked, a board holds all seven
    seats, each what its kind says, with no database: blue's optimal, red's
    on the other side of a sided map, the two current comps, the fill around
    the lock and the countered case. Without a blue pick there is no fill and
    no countered case."""
    from inference import engine
    from inference.result import Momentum
    from inference.shapes import legal_shapes
    b = engine.board(synthetic_world, Draft("Harbor Gate", ("Anvil",), ("Balm",), side="attack"),
                     catalog=scratch_playbook)
    assert b.blue.kind == "infer" and b.blue.side == "attack"
    assert b.red.seat == "red" and b.red.side == "defense"
    assert b.current.partial and b.current.blue == ["Balm"]
    assert b.fill.kind == "fill" and len(b.fill.picks) == 6 and "Balm" in b.fill.blue
    assert b.countered.kind == "countered" and b.countered.red == b.red.blue
    assert set(b.momentum) == set(Momentum.__annotations__)
    assert b.plan.split("\n")[-1].startswith("Based on: ")
    assert b.shapes == [list(s) for s in legal_shapes(scratch_playbook)]
    seats = (b.blue, b.red, b.current, b.red_current, b.fill, b.countered, b.expected)
    assert not any("facts" in r.to_dict() for r in seats)
    alone = engine.board(synthetic_world, Draft("Harbor Gate", ("Anvil",), side="attack"),
                         catalog=scratch_playbook)
    assert alone.fill is None and alone.countered is None


def test_a_newer_board_from_the_same_client_supersedes_the_older_one(
        synthetic_world, scratch_playbook):
    """The page's boards take a ticket per client: a newer ticket supersedes
    the older one under the same name only, and a board whose ticket is
    superseded stops before its first search, in this process too."""
    from inference import engine, supersede
    latest = supersede.Latest()
    first, elsewhere = latest.take("tab-1"), latest.take("tab-2")
    assert not first() and not elsewhere()
    second = latest.take("tab-1")
    assert first() and not second() and not elsewhere()
    with pytest.raises(supersede.Superseded):
        engine.board(synthetic_world, Draft("Harbor Gate", ("Anvil",), ("Balm",)),
                     catalog=scratch_playbook, brief=engine.Brief(superseded=first))


def _shortfall(world, result):
    """matchup.heal_shortfall of a result's six against its red, as scored."""
    six = [world.hero(n) for n in result.blue]
    red = [world.hero(n) for n in result.red]
    return compute.matchup_metrics(world, team_metrics(world, six, None, red),
                                   team_metrics(world, red, None, ()))["heal_shortfall"]


def test_the_healing_floor_scores_on_top_of_the_engine_and_off_leaves_it_alone(
        synthetic_world, tmp_path):
    """The floor is a playbook term, not the engine's: under DEFAULT it sits
    on the three base terms, and under OFF it scores alone, the base terms
    gone and the rule's charge the whole score. Its bar cites the board's
    healing-floor fact. With the rule the optimal clears the floor; the
    engine alone does not see it, and OFF with the assumptions alone scores
    nothing."""
    from inference import engine
    w = synthetic_world
    heal = heal_rate(str(tmp_path))
    draft = Draft("Harbor Gate", side="attack")
    plain = engine.infer(w, draft, catalog=ASSUMPTIONS_ONLY)
    floored = engine.infer(w, draft, catalog=heal)
    terms = {c["id"]: c for c in floored.contributions}
    assert set(terms) == {"base.rates", "base.synergy", "base.counters", "heal-rate"}
    rule = terms["heal-rate"]
    assert rule["form"] == "scored" and rule["weighted"] == -2.0 * _shortfall(w, floored)
    assert rule["text"].startswith("healing floor: blue heals ")
    # the engine alone fields Kite and Anvil, Balm and Tansy: 115 a second on
    # 2325 against a need of 134.3; the floor trades Kite and Tansy for Mortar
    # and Myrrh and clears it
    assert _shortfall(w, plain) > 0.1 and _shortfall(w, floored) == 0.0
    alone = engine.infer(w, draft, catalog=heal, base=OFF)
    assert [c["id"] for c in alone.contributions] == ["heal-rate"]
    assert alone.score == -2.0 * _shortfall(w, alone) == 0.0
    assert scores(heal, OFF) and not scores(ASSUMPTIONS_ONLY, OFF)
    assert DEFAULT.on and not OFF.on


@pytest.mark.invariant
def test_the_healing_floor_takes_kings_row_off_one_support(world, tmp_path):
    """King's Row attack, red empty: the default engine alone fields one
    support, Zenyatta on Reinhardt, Genji, Hanzo, Vendetta and Widowmaker,
    0.74 under the floor. The shipped floor (HEAL_RATE, written to a folder of
    its own) seats a second support and leaves the six under 0.15."""
    from inference import engine
    draft = Draft("King's Row", side="attack")
    plain = engine.infer(world, draft, catalog=ASSUMPTIONS_ONLY)
    floored = engine.infer(world, draft, catalog=heal_rate(str(tmp_path)))

    def supports(result):
        return sum(1 for n in result.blue if world.hero(n).role == "support")

    assert supports(plain) == 1 and _shortfall(world, plain) > 0.5
    assert supports(floored) >= 2 and _shortfall(world, floored) < 0.15
