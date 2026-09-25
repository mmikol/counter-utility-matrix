"""Record a board per released hero that seats it, for the reach test.

Runs inference.reach.search for every released hero, in name order, on the
built database, the playbook in force and the default engine, and writes the
boards it finds to tests/fixtures/reach.json beside that playbook's digest and
the engine's stamp (inference.base.stamp). Minutes of solving in one process.
Run from the repo root:

    .venv/bin/python -m scripts.reach

It prints the heroes no board seats, each with the gap it fell short by, so
UNSEATED in tests/inference/test_reach.py can be checked against them.
"""
import json
import os

import psycopg

from db import ROOT, psql
from facts import tables
from inference import base, catalog, reach

OUT = os.path.join(ROOT, "tests", "fixtures", "reach.json")


def main() -> int:
    """Search every released hero, record the boards that seat one -> 0."""
    with psycopg.connect(psql.default_dsn()) as cx:
        world = tables.load(cx)
    seated: list[reach.Reach] = []
    unseated: list[str] = []
    for hero in sorted((h for h in world.heroes.values() if h.released), key=lambda h: h.name):
        found = reach.search(world, hero.name)
        if not found["seated"]:
            unseated.append("%s %.3f" % (hero.name, found["gap"]))
        else:
            seated.append(found)
    playbook = catalog.playbook_digest()
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump({"playbook": playbook, "base": base.stamp(base.DEFAULT), "boards": seated},
                  handle, indent=1)
    print(
        "recorded %d seated heroes under playbook %s and the default engine, %d of them after"
        " bans; unseated: %s"
        % (
            len(seated), playbook[:12], sum(1 for b in seated if b["banned"]),
            ", ".join(unseated) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
