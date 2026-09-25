"""The inference layer's tests, the reference playbook they prove the solver against, its
assumptions alone (ASSUMPTIONS_ONLY) for a test that needs a playbook that scores nothing,
the proven fixtures, each read with the objective it was recorded under and compared with
the one in force, and timeless(), a board's payload less the seconds each result took, for
comparing two solves."""

import json
import os
import re
from typing import Any, TypedDict

import pytest

from db import ROOT
from inference import base, catalog

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
# the former shipped playbook - every kind and every form - kept as the reference the
# solver's behaviours are proven against; the live playbook is the user's own
FIXTURE_PLAYBOOK = os.path.join(FIXTURES, "playbook")
# the reference playbook's four assumptions (locked-picks, objective, optimal-play,
# vintage): a playbook that scores nothing and writes no limit. A board's weights
# reach heuristics alone, so the shared list is never weighted in place
ASSUMPTIONS_ONLY = [s for s in catalog.load(FIXTURE_PLAYBOOK) if s.kind == "assumption"]
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


class Recorded(TypedDict):
    """A proven fixture: the objective it was recorded under - the playbook's
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
