"""infer() and evaluate(): locked picks and the queue's shape, an answer to a
flier, a full six ranked against its field, a board no six satisfies, bans,
one scale per board, an announced hero, the fill that keeps a lock, a
seat's search timed from where it began, and no rank in an unscored field."""

import os

import pytest

from db import Refusal
from inference import catalog
from tests.inference import FIXTURE_PLAYBOOK
from ui.facts import board_facts
from ui.facts.draft import Draft


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
    """A scored six is ranked against the field; under a playbook that scores
    nothing every six ties, and none is ranked."""
    from inference import engine
    six = ("Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio")
    draft = Draft("King's Row", ("Zarya", "Pharah"), six)
    r = engine.evaluate(world, draft, catalog=catalog.load(FIXTURE_PLAYBOOK))
    assert r.rank >= 1 and r.kind == "evaluate" and len(r.picks) == 6
    shipped = engine.evaluate(world, draft)
    assert shipped.rank is None if shipped.unscored() else shipped.rank >= 1
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


def test_a_seat_solved_across_the_pool_is_timed_from_when_its_search_began(
        synthetic_world, scratch_playbook):
    """A board's seat takes its Solved from a split that ran before the seat
    is written up, so its seconds run from when the split was sent out: the
    pooled search counts, and a seat reads the time the board took."""
    import time

    from inference import engine, parallel
    from inference.solver import Solver
    draft = Draft("Harbor Gate", ("Anvil",), side="attack")
    m, red_h, _, _ = synthetic_world.resolve(draft.map_name, draft.red, (), ())
    solved = Solver(synthetic_world, m, red=red_h, locked=[], side="attack",
                    catalog=scratch_playbook).solve(top=2)
    seat = engine._optimal(synthetic_world, draft, catalog=scratch_playbook, pool_size=6, top=1,
                           seat="blue", kind="infer", solved=solved, began=time.time() - 5)
    assert seat.result.seconds >= 5 and seat.result.to_dict()["seconds"] >= 5
    alone = engine._optimal(synthetic_world, draft, catalog=scratch_playbook, pool_size=6,
                            top=1, seat="blue", kind="infer", solved=None, began=None)
    assert alone.result.seconds < 5 and parallel.NullSplit.started is None


def test_a_six_in_a_field_that_scores_nothing_has_no_rank(
        synthetic_world, scratch_playbook, tmp_path):
    """evaluate counts the sixes that score strictly higher, and where the
    playbook scores nothing every six ties at zero, so every six ranked first.
    An unscored six now carries no rank; a scored one keeps its place."""
    import shutil

    from inference import engine
    six = ("Anvil", "Kite", "Rook", "Needle", "Balm", "Tansy")
    limit_only = tmp_path / "limit-only"            # the scratch playbook is tmp_path's own
    limit_only.mkdir()
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, "open-queue-tanks.md"), limit_only)
    unscored = engine.evaluate(synthetic_world, Draft("Harbor Gate", (), six, side="attack"),
                               catalog=catalog.load(str(limit_only)))
    assert unscored.unscored() is not None
    assert unscored.rank is None and unscored.to_dict()["rank"] is None
    assert "(rank " not in unscored.rendered() and "UNSCORED" in unscored.rendered()
    scored = engine.evaluate(synthetic_world, Draft("Harbor Gate", (), six, side="attack"),
                             catalog=scratch_playbook)
    assert scored.unscored() is None and scored.rank >= 1
    assert "(rank %d among the feasible field)" % scored.rank in scored.rendered()
