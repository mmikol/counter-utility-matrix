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

from inference import catalog, engine
from tests.inference import FIXTURES

FIXTURE = os.path.join(FIXTURES, "optimal.json")


def _boards():
    with open(FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)


@pytest.mark.invariant
def test_the_solver_reaches_the_proven_maximum(world):
    # the boards were proven under the 239 rules 9328429 removed; a playbook that
    # scores nothing ties every six at zero and has no maximum to reach. When rules
    # return this runs again and fails until the boards are re-proven under them.
    if not catalog.has_scoring_terms(catalog.load()):
        pytest.skip("the shipped playbook scores nothing: no optimum to reach")
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


def test_the_proven_boards_cover_every_input():
    """A regression set that exercised one shape would gate nothing. Bans are
    not among the shapes: a board proved under the old scale was proved against
    an objective that read the bans, so scripts/optimal.py holds them out
    (OPTIMAL_STALE_BANNED) until they are enumerated again. Needs no database -
    it reads the fixture - so the pull-request gate checks it."""
    boards = [row["board"] for row in _boards()]
    assert len({b["map"] for b in boards}) >= 5
    assert {len(b["red"]) for b in boards} >= {0, 2}
    assert max(len(b["locked"]) for b in boards) >= 2
    assert not any(b["bans"] for b in boards), "re-proven with bans: restore the bans clause"
