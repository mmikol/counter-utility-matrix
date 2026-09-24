"""Record the true maximum of a set of boards, by enumerating every legal six.

Offline: minutes a board. Reads the brute force's .jsonl output - the paths
named by OPTIMAL_SOURCES, separated the way PATH is - and writes
tests/fixtures/optimal.json, which tests/inference/test_optimal.py then checks
the solver still reaches. Run from the repo root:

    OPTIMAL_SOURCES=~/countrix-study/brute/proof100.jsonl .venv/bin/python -m scripts.optimal

OPTIMAL_KEEP caps the boards kept (20), and OPTIMAL_STALE_BANNED=0 lets the
boards with bans back in once they are proven again (it is 1, holding them
out, by default).

The fixture records the digest of the playbook in force (COUNTRIX_STRATEGIES
selects another), and the gate refuses boards proved under a different one, so
that playbook must be the one the enumeration ran under.
"""
import json
import os
from collections.abc import Sequence
from typing import TypedDict

from db import ROOT
from inference import catalog

OUT = os.path.join(ROOT, "tests", "fixtures", "optimal.json")


class BoardInputs(TypedDict):
    """A board as the brute force enumerated it: what the solver is handed."""
    map: str
    side: str | None
    red: list[str]
    bans: list[str]
    locked: list[str]


class Proof(TypedDict):
    """One proven board: the six the enumeration found best, what it scored, and
    whether that six holds a hero the search's pool cut."""
    board: BoardInputs
    six: list[str]
    score: float
    needed_outside: bool


def read_proofs(paths: Sequence[str], stale_banned: bool) -> list[Proof]:
    """The exact proofs in the brute force's .jsonl files, in file order."""
    rows: list[Proof] = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                # a board's proof is only as current as the objective it was
                # enumerated under; stale_banned says the banned boards predate
                # the scale going ban-blind, and are out until re-proven
                if stale_banned and row["board"].get("bans"):
                    continue
                if row.get("exact") and "true_six" in row:
                    rows.append({"board": row["board"], "six": row["true_six"],
                                 "score": row["true_score"],
                                 "needed_outside": bool(row.get("true_six_outside_pool"))})
    return rows


def spread(rows: list[Proof], keep: int) -> list[Proof]:
    """At most `keep` proofs, one per map and input shape (red, bans and locked
    counts), the boards that need a hero outside the pool first."""
    # A board only passes because of the search if its winner held a hero the pool
    # had cut; a set without those cannot tell a working two-swap from a deleted
    # one. Take those first, then spread the rest over maps and input shapes.
    ordered = sorted(rows, key=lambda r: (not r["needed_outside"], r["board"]["map"],
                                          len(r["board"]["red"]), len(r["board"]["bans"]),
                                          len(r["board"]["locked"])))
    seen: set[tuple[str, int, int, int]] = set()
    kept: list[Proof] = []
    for row in ordered:
        if len(kept) >= keep:
            break
        b = row["board"]
        shape = (b["map"], len(b["red"]), len(b["bans"]), len(b["locked"]))
        if shape not in seen:
            seen.add(shape)
            kept.append(row)
    return kept


def main() -> int:
    """Record the spread of the proofs OPTIMAL_SOURCES names -> 0; the run stops
    when there is nothing to record or the kept set would make a vacuous gate."""
    # the enumerations live outside the repo - hours of compute a file, kept
    # where they were produced
    sources = [
        os.path.expanduser(p) for p in os.environ.get("OPTIMAL_SOURCES", "").split(os.pathsep) if p]
    keep = int(os.environ.get("OPTIMAL_KEEP", "20"))
    stale_banned = os.environ.get("OPTIMAL_STALE_BANNED", "1") == "1"
    if not sources:
        raise SystemExit("set OPTIMAL_SOURCES to the brute force's .jsonl files"
                         " (%s-separated)" % os.pathsep)
    missing = [path for path in sources if not os.path.exists(path)]
    if missing:
        raise SystemExit("no such file: %s" % ", ".join(missing))
    rows = read_proofs(sources, stale_banned)
    if not rows:
        raise SystemExit("no proven boards yet - run the brute force first")
    kept = spread(rows, keep)
    hard = sum(1 for r in kept if r["needed_outside"])
    if not hard:
        raise SystemExit("no kept board needs a hero outside the pool: the gate would be "
                         "vacuous - the search could be deleted and it would still pass")
    playbook = catalog.playbook_digest()
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump({"playbook": playbook, "boards": kept}, handle, indent=1)
    print(
        "recorded %d proven boards over %d maps under playbook %s; %d of them need a hero"
        " the pool cut" % (len(kept), len({r["board"]["map"] for r in kept}), playbook[:12], hard))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
