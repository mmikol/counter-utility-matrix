"""Validation: our data against what third parties publish.

Never equality - every source samples a different population - and never a
hard failure on their side: an unreachable or redesigned page skips.
"""

import json
import re

import pytest

pytestmark = [pytest.mark.invariant, pytest.mark.validation]

PER_ROLE = 3


def _normalise(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def test_owherostats_best_map_rankings_broadly_agree(fetch, rows):
    """Overlap of top-9-per-map sets, floor 40%.

    Ours is scoped to the all-ranks tier: map_meta holds every rank, and an
    unscoped ranking once silently mixed nine populations and dropped
    agreement from 62% to 27%.
    """
    html = fetch("https://owherostats.com/maps/best").text
    published = {}
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                            html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if data.get("@type") == "ItemList" and data.get("name", "").startswith(
                "Best heroes on"):
            published[_normalise(data["name"].replace("Best heroes on ", ""))] = [
                item["name"] for item in data["itemListElement"]]
    if not published:
        pytest.skip("owherostats no longer publishes ItemList data")

    ranked = rows("""
        select mp.name, r.name, h.name,
               row_number() over (partition by mp.map_id, r.role_id
                                  order by m.win_rate desc)
        from map_meta m
        join heroes h using(hero_id) join roles r using(role_id)
        join maps mp on mp.map_id = m.map_id
        join competitive_tiers t on t.tier_id = m.tier_id
        where t.code = 'all'""")
    ours = {}
    for map_name, role, hero, rank in ranked:
        if rank <= PER_ROLE:
            ours.setdefault(_normalise(map_name), set()).add(_normalise(hero))

    matched = total = 0
    for map_name, heroes in published.items():
        mine = ours.get(map_name.replace("antartic", "antarctic"))
        if not mine:
            continue
        matched += len({_normalise(h) for h in heroes} & mine)
        total += len(heroes)
    assert total, "nothing comparable was published"
    assert matched / total >= 0.40, (
        "only %.0f%% of their picks appear in ours" % (100 * matched / total))


def test_overfast_roster_matches_ours(fetch, rows):
    """OverFast is never used by the pipeline - validation only."""
    theirs = fetch("https://overfast-api.tekrop.fr/heroes").json()
    their_names = {_normalise(h["name"]) for h in theirs}
    ours = {_normalise(r[0]) for r in rows("select name from heroes")}
    if not their_names:
        pytest.skip("overfast returned no heroes")
    overlap = len(ours & their_names) / len(ours)
    assert overlap >= 0.85, "only %.0f%% roster overlap" % (100 * overlap)
