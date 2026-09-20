"""The boards whose true maximum is known.

Proving one costs a full enumeration of every legal six - about 18 million
candidates, minutes of CPU - so it is done offline and the answer recorded.
`tests/fixtures/optimal.json` holds, per board, the six a brute force found and
what it scored. This re-solves each and checks the solver still reaches it.

It is the regression gate on the search: a change that quietly stops finding a
two-swap, or narrows the pool, or breaks a constraint, shows up here as a board
that used to be exact and is not. Regenerate with `scripts/optimal.py` after a
deliberate change to the objective, and say in the commit why every number moved.
"""
import json
import os

import pytest

from inference import engine

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "fixtures", "optimal.json")


@pytest.fixture(scope="module")
def world(db):
    from ui.facts import model
    w = model.load(db)
    db.rollback()
    return w


def _boards():
    with open(FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)


@pytest.mark.invariant
def test_the_solver_reaches_the_proven_maximum(world):
    proven = _boards()
    assert proven, "no proven boards recorded"
    missed = []
    for row in proven:
        b = row["board"]
        got = engine.infer(world, b["map"], b["red"], b["locked"],
                           side=b["side"], bans=b["bans"], top=1)
        if sorted(got.blue) != row["six"] or abs(got.score - row["score"]) > 1e-6:
            missed.append("%s %s red=%d ban=%d lock=%d: %.6f %s, proven %.6f %s"
                          % (b["map"], b["side"] or "-", len(b["red"]), len(b["bans"]),
                             len(b["locked"]), got.score, sorted(got.blue),
                             row["score"], row["six"]))
    assert not missed, "the solver no longer reaches the proven maximum:\n  " + "\n  ".join(missed)


@pytest.mark.invariant
def test_the_proven_boards_cover_every_input(world):
    """A regression set that exercised one shape would gate nothing."""
    boards = [row["board"] for row in _boards()]
    assert len({b["map"] for b in boards}) >= 5
    assert {len(b["red"]) for b in boards} >= {0, 2}
    assert max(len(b["bans"]) for b in boards) >= 2
    assert max(len(b["locked"]) for b in boards) >= 2
