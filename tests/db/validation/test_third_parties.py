"""Validation: our data against what third parties publish.

Never equality - every source samples a different population - and never a
hard failure on their side: an unreachable or redesigned page skips.
(owherostats stopped publishing its best-map lists as structured data, so
the test that read them always skipped and is gone; a comparison that
never runs tests nothing.)
"""

import re

import pytest

pytestmark = [pytest.mark.invariant, pytest.mark.validation]



def _normalise(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def test_overfast_roster_matches_ours(fetch, rows):
    """OverFast is never used by the pipeline - validation only."""
    theirs = fetch("https://overfast-api.tekrop.fr/heroes").json()
    their_names = {_normalise(h["name"]) for h in theirs}
    ours = {_normalise(r[0]) for r in rows("select name from heroes")}
    if not their_names:
        pytest.skip("overfast returned no heroes")
    overlap = len(ours & their_names) / len(ours)
    assert overlap >= 0.85, "only %.0f%% roster overlap" % (100 * overlap)
