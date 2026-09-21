"""Record the true maximum of a set of boards, by enumerating every legal six.

Offline: minutes a board. Reads the brute force's .jsonl output - the paths
named by OPTIMAL_SOURCES, separated the way PATH is - and writes
tests/fixtures/optimal.json, which tests/inference/test_optimal.py then checks
the solver still reaches.

    OPTIMAL_SOURCES=~/countrix-study/brute/proof100.jsonl python scripts/optimal.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the enumerations live outside the repo - hours of compute a file, kept
# where they were produced
SOURCES = [os.path.expanduser(p)
           for p in os.environ.get("OPTIMAL_SOURCES", "").split(os.pathsep) if p]
OUT = os.path.join(ROOT, "tests", "fixtures", "optimal.json")
KEEP = int(os.environ.get("OPTIMAL_KEEP", "20"))
STALE_BANNED = os.environ.get("OPTIMAL_STALE_BANNED", "1") == "1"


def main():
    if not SOURCES:
        raise SystemExit("set OPTIMAL_SOURCES to the brute force's .jsonl files"
                         " (%s-separated)" % os.pathsep)
    rows = []
    for path in SOURCES:
        if not os.path.exists(path):
            raise SystemExit("no such file: %s" % path)
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                # a board's proof is only as current as the objective it was
                # enumerated under; STALE_BANNED says the banned boards predate
                # the scale going ban-blind, and are out until re-proven
                if STALE_BANNED and row["board"].get("bans"):
                    continue
                if row.get("exact") and "true_six" in row:
                    rows.append({"board": row["board"], "six": row["true_six"],
                                 "score": row["true_score"],
                                 "needed_outside": bool(row.get("true_six_outside_pool"))})
    if not rows:
        raise SystemExit("no proven boards yet - run the brute force first")
    # A board only passes because of the search if its winner held a hero the pool
    # had cut; a set without those cannot tell a working two-swap from a deleted
    # one. Take those first, then spread the rest over maps and input shapes.
    rows.sort(key=lambda r: (not r.get("needed_outside"), r["board"]["map"],
                             len(r["board"]["red"]), len(r["board"]["bans"]),
                             len(r["board"]["locked"])))
    seen, kept = set(), []
    for row in rows:
        b = row["board"]
        key = (b["map"], len(b["red"]), len(b["bans"]), len(b["locked"]))
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
        if len(kept) >= KEEP:
            break
    hard = sum(1 for r in kept if r.get("needed_outside"))
    if not hard:
        raise SystemExit("no kept board needs a hero outside the pool: the gate would be "
                         "vacuous - the search could be deleted and it would still pass")
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(kept, handle, indent=1)
    print("recorded %d proven boards over %d maps; %d of them need a hero the pool cut"
          % (len(kept), len({r["board"]["map"] for r in kept}), hard))


if __name__ == "__main__":
    main()
