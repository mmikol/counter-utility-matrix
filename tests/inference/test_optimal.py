"""The boards whose true maximum is known.

Proving one costs a full enumeration of every legal six - about 18 million
candidates, minutes of CPU - so it is done offline and the answer recorded.
`tests/fixtures/optimal.json` holds, per board, the six a brute force found and
what it scored, beside the digest of the playbook it was proved under. This
re-solves each and checks the solver still reaches it.

It is the real-World gate, dormant: the boards were proved under a playbook
that no longer exists, so it skips until they are re-proven (pm/backlog.md). The
enumeration that gates the search in CI is
test_the_search_reaches_the_enumerated_maximum in test_solver.py, on synthetic
boards. Regenerate with `.venv/bin/python -m scripts.optimal` after a deliberate
change to the objective, and say in the commit why every number moved.
The recorder's own choices - which proofs it takes and which it holds out - are
tested here too, on rows written for the test.
"""
import json
import os
import re

import pytest

from facts.draft import Draft
from inference import catalog, engine
from scripts import optimal
from tests.inference import recorded


@pytest.mark.invariant
def test_the_solver_reaches_the_proven_maximum(world):
    # the boards were proven under the 239 rules 9328429 removed, and the fixture
    # names that playbook; a playbook that scores nothing ties every six at zero and
    # has no maximum to reach. When rules return this fails at the digest until the
    # boards are re-proven under them.
    if not catalog.has_scoring_terms(catalog.load()):
        pytest.skip("the shipped playbook scores nothing: no optimum to reach")
    proven = recorded("optimal")
    in_force = catalog.playbook_digest()
    assert proven["playbook"] == in_force, (
        "recorded under a different playbook (%s, in force %s): re-prove the boards"
        % (proven["playbook"][:12], in_force[:12]))
    missed = []
    for row in proven["boards"]:
        b = row["board"]
        got = engine.infer(world, Draft(b["map"], tuple(b["red"]), tuple(b["locked"]),
                                        tuple(b["bans"]), b["side"]), top=1)
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
    it reads the fixture, its playbook digest included - so the pull-request
    gate checks it."""
    boards = [row["board"] for row in recorded("optimal")["boards"]]
    assert len({b["map"] for b in boards}) >= 5
    assert {len(b["red"]) for b in boards} >= {0, 2}
    assert max(len(b["locked"]) for b in boards) >= 2
    assert not any(b["bans"] for b in boards), "re-proven with bans: restore the bans clause"


SIX = ["Ana", "Juno", "Mei", "Reinhardt", "Sojourn", "Tracer"]


def _proof(map_name, red=0, bans=0, locked=0, outside=False):
    return {"board": {"map": map_name, "side": None, "red": ["Ana"] * red,
                      "bans": ["Mercy"] * bans, "locked": ["Mei"] * locked},
            "six": SIX, "score": 1.5, "needed_outside": outside}


def _brute_force_rows(path, *rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return str(path)


def test_the_recorder_takes_the_boards_the_pool_cut_first_and_one_per_shape():
    plain = _proof("Busan", red=1)
    cut = _proof("Busan", red=1, outside=True)
    two_red = _proof("Busan", red=2)
    locked = _proof("Busan", red=2, locked=1)
    ilios = _proof("Ilios")
    rows = [plain, ilios, two_red, cut, locked]
    # the cut board takes its shape from the plain one; a lock or a second red is a
    # shape of its own
    assert optimal.spread(rows, 10) == [cut, two_red, locked, ilios]
    assert optimal.spread(rows, 2) == [cut, two_red]
    assert optimal.spread(rows, 0) == []


def test_the_recorder_holds_out_banned_and_unproven_rows(tmp_path):
    board = {"map": "Busan", "side": "attack", "red": [], "bans": [], "locked": []}
    banned = dict(board, bans=["Mercy"])
    path = _brute_force_rows(
        tmp_path / "proof.jsonl",
        {"board": banned, "exact": True, "true_six": SIX, "true_score": 3.0},
        {"board": board, "exact": False, "true_six": SIX, "true_score": 2.0},
        {"board": board, "exact": True},
        {
            "board": board, "exact": True, "true_six": SIX, "true_score": 1.0,
            "true_six_outside_pool": True})
    proven = {"board": board, "six": SIX, "score": 1.0, "needed_outside": True}
    assert optimal.read_proofs([path], stale_banned=True) == [proven]
    assert optimal.read_proofs([path], stale_banned=False) == [
        {"board": banned, "six": SIX, "score": 3.0, "needed_outside": False}, proven]


def test_the_recorder_stamps_the_playbook_in_force_and_refuses_a_vacuous_gate(
        tmp_path, monkeypatch):
    board = {"map": "Busan", "side": "attack", "red": [], "bans": [], "locked": []}
    source, gone = tmp_path / "proof.jsonl", tmp_path / "gone.jsonl"
    source.write_text("not json\n", encoding="utf-8")
    monkeypatch.setattr(optimal, "OUT", str(tmp_path / "optimal.json"))
    monkeypatch.delenv("OPTIMAL_SOURCES", raising=False)
    with pytest.raises(SystemExit, match="set OPTIMAL_SOURCES"):
        optimal.main()
    # every path is checked before any is read: the first file is never parsed
    monkeypatch.setenv("OPTIMAL_SOURCES", os.pathsep.join((str(source), str(gone))))
    with pytest.raises(SystemExit, match="no such file: %s" % re.escape(str(gone))):
        optimal.main()
    monkeypatch.setenv("OPTIMAL_SOURCES", str(source))
    _brute_force_rows(source, {"board": board, "exact": True, "true_six": SIX,
                               "true_score": 1.0})
    with pytest.raises(SystemExit, match="vacuous"):
        optimal.main()
    _brute_force_rows(source, {"board": board, "exact": True, "true_six": SIX,
                               "true_score": 1.0, "true_six_outside_pool": True})
    assert optimal.main() == 0
    written = json.loads((tmp_path / "optimal.json").read_text(encoding="utf-8"))
    assert written == {"playbook": catalog.playbook_digest(),
                       "boards": [{"board": board, "six": SIX, "score": 1.0,
                                   "needed_outside": True}]}
