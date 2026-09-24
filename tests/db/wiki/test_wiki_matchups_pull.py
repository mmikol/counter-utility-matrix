"""The counters pulled from the wiki page cache: run() inside a transaction
that is rolled back, the table it fills and the counters the wiki is known
to state. Skipped without the cache or the database."""

import os

import pytest

from db import CACHE_DIRS
from db.data.fetch import PullContext
from db.data.wiki import matchups

needs_cache = pytest.mark.skipif(
    not os.path.isdir(CACHE_DIRS["wiki"]), reason="the wiki page cache is not on this machine")


# --- the page cache -> the table ---------------------------------------------

@needs_cache
@pytest.mark.invariant
def test_counters_pull_from_the_cache(sandbox):
    data = matchups.run(sandbox, PullContext(CACHE_DIRS["wiki"], log=lambda _: None))
    rows = sandbox.execute(
        "select c.hero_id, c.countered_by_id, src.code from counters c"
        " join sources src using (source_id)").fetchall()
    assert data["tables"] == ["counters"] and data["unmatched"] == [] and data["missing"] == []
    assert {row[2] for row in rows} == {"wiki"}

    edges = [row[:2] for row in rows]
    assert len(set(edges)) == len(edges) and all(loser != winner for loser, winner in edges)
    assert not any(edge[::-1] in set(edges) for edge in edges)

    # Measured on the cache of 2026-09: 340 edges from 46 articles, 1260 written
    # cells of which 72 rated and 860 with no verdict; a hero answers 0..15 others
    # (Bastion most) and is answered by 0..22 (Doomfist most); D.Mon and Shion,
    # whose articles have no written cell, have no edge.
    assert data["counters"] == len(edges) > 300
    assert data["articles"] >= 45 and data["cells"] > 1200 and data["rated"] >= 60
    assert 0 < data["no_verdict"] < data["cells"]
    released = dict(sandbox.execute(
        "select hero_id, name from heroes where status = 'released'").fetchall())
    in_an_edge = {hero_id for edge in edges for hero_id in edge}
    assert in_an_edge <= set(released)
    assert data["no_edge"] == sorted(name for hero_id, name in released.items()
                                     if hero_id not in in_an_edge)
    assert len(data["no_edge"]) <= 3
    assert set(data["no_edge"]) <= set(data["unwritten"]) < set(released.values())
    answered = {hero_id for _, hero_id in edges}
    assert len(answered) >= len(released) - 5          # nearly every hero answers someone
    assert max(sum(1 for edge in edges if edge[1] == hero_id) for hero_id in released) < 25
    assert max(sum(1 for edge in edges if edge[0] == hero_id) for hero_id in released) < 30


@needs_cache
@pytest.mark.invariant
def test_the_wiki_states_the_well_known_counters(sandbox):
    data = matchups.run(sandbox, PullContext(CACHE_DIRS["wiki"], log=lambda _: None))
    answers = {(winner, loser) for winner, loser in sandbox.execute(
        "select w.name, l.name from counters c join heroes w on w.hero_id = c.countered_by_id"
        " join heroes l on l.hero_id = c.hero_id")}
    stated = [
        # Winston: "you serve an excellent counter to Widowmaker"; Widowmaker: "Winston is
        # one of your biggest threats."
        ("Winston", "Widowmaker"),
        ("Winston", "Genji"),        # Winston: "one of the strongest counters to Genji"
        ("Reaper", "Winston"),       # Winston: "Reaper is one of your worst nightmares."
        ("Roadhog", "Winston"),      # Winston: "Roadhog will prove to be one of your worst enemies"
        ("Sombra", "Widowmaker"),    # Widowmaker: "Sombra is one of your biggest counters"
        ("D.Va", "Widowmaker"),      # Widowmaker: "D.Va is a significant threat to Widowmaker"
        ("Widowmaker", "Pharah"),    # Widowmaker: "a prime target for you at a distance"
        ("Pharah", "Junkrat"),       # Pharah: "Pharah is the ultimate hard counter to Junkrat."
        ("Soldier: 76", "Pharah"),   # Pharah: "one of Pharah's most notorious counters"
        ("D.Va", "Pharah"),          # Pharah: rated VERY WEAK MATCHUP | EXTREME RISK
        ("Pharah", "Reinhardt"),     # Pharah: rated VERY STRONG MATCHUP | LOW RISK
        ("Ana", "Wuyang"),           # Wuyang: "Biotic Grenade is a brutal hard counter to Wuyang"
    ]
    for winner, loser in stated:
        assert (winner, loser) in answers and (loser, winner) not in answers, (winner, loser)

    # Articles that contradict each other leave no edge either way.
    assert data["contradicted"]
    for pair in data["contradicted"]:
        hero, other = pair.split(" / ")
        assert (hero, other) not in answers and (other, hero) not in answers
