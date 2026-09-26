"""The inference layer's tests, the reference playbook they prove the solver against, its
assumptions alone (ASSUMPTIONS_ONLY) for a test that needs a playbook that scores nothing,
the shipped healing floor's fields (HEAL_RATE) and heal_rate(), a playbook of that rule
alone written where a test says, so no solver test reads inference/strategies/, the
recorded fixture, read with the objective it was recorded under and compared with the
one in force, and timeless(), a board's payload less the seconds each result took, for
comparing two solves."""

import json
import os
import re
from typing import Any, TypedDict

import pytest

from db import ROOT
from inference import base, catalog
from inference.strategy import Strategy

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
# the former shipped playbook - every kind and every form - kept as the reference the
# solver's behaviours are proven against; the live playbook is the user's own
FIXTURE_PLAYBOOK = os.path.join(FIXTURES, "playbook")
# the reference playbook's four assumptions (locked-picks, objective, optimal-play,
# vintage): a playbook that scores nothing and writes no limit. A board's weights
# reach heuristics alone, so the shared list is never weighted in place
ASSUMPTIONS_ONLY = [s for s in catalog.load(FIXTURE_PLAYBOOK) if s.kind == "assumption"]
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
# the frontmatter of inference/strategies/heal-rate.md, which test_catalog holds
# the shipped file to
HEAL_RATE = {
    "kind": "constraint", "category": "sustain", "weight": 2.0,
    "penalty": "matchup.heal_shortfall"}


def heal_rate(directory: str) -> list[Strategy]:
    """The shipped healing floor as a playbook of its own, in `directory`: a
    file with HEAL_RATE's fields, read back through the catalog."""
    fields = "".join("%s: %s\n" % (k, v) for k, v in HEAL_RATE.items())
    with open(os.path.join(directory, "heal-rate.md"), "w", encoding="utf-8") as handle:
        handle.write("---\nname: Heal at the other side's rate\n%s---\n# Heal at the other"
                     " side's rate\n\nThe healing floor.\n" % fields)
    return catalog.load(directory)


class Recorded(TypedDict):
    """A recorded fixture: the objective it was recorded under - the playbook's
    digest (catalog.playbook_digest) and the default engine's stamp
    (base.stamp, None with the engine off) - and its boards as the recorder
    wrote them."""
    playbook: str
    base: dict[str, float] | None
    boards: list[dict[str, Any]]


def recorded(name: str) -> Recorded:
    """tests/fixtures/<name>.json. A fixture that names no playbook or no
    engine, or holds no boards, fails the test that reads it."""
    with open(os.path.join(FIXTURES, "%s.json" % name), encoding="utf-8") as handle:
        fixture = json.load(handle)
    if not (isinstance(fixture, dict) and isinstance(fixture.get("playbook"), str)
            and DIGEST_RE.match(fixture["playbook"])):
        pytest.fail("tests/fixtures/%s.json names no playbook digest: re-record it" % name)
    if "base" not in fixture:
        pytest.fail("tests/fixtures/%s.json names no default engine: re-record it" % name)
    if not fixture.get("boards"):
        pytest.fail("tests/fixtures/%s.json records no boards" % name)
    return Recorded(playbook=fixture["playbook"], base=fixture["base"], boards=fixture["boards"])


def in_force() -> tuple[str, base.BaseStamp | None]:
    """The objective a board is solved under by default: the playbook in
    force's digest and the default engine's stamp, as a fixture records them."""
    return catalog.playbook_digest(), base.stamp(base.DEFAULT)


def timeless(payload: dict[str, Any]) -> dict[str, Any]:
    """A board's payload (its to_dict(), or the JSON a server sent) less the
    seconds each result took: 'seconds' popped from every dict value holding
    one. The payload is changed in place and returned."""
    for value in payload.values():
        if isinstance(value, dict) and "seconds" in value:
            value.pop("seconds")
    return payload
