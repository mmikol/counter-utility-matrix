"""Every hero is the right pick somewhere: the playbook may make a hero rare, never
impossible. tests/fixtures/reach.json records, per released hero, the board
inference.reach.search seated it on (a tool: `reach`), within the five bans a match has. Rates
move daily and the two databases differ, so a few boards
may tip; a hero that falls off its board is searched for again, and none may be lost."""

import json
import os

import pytest

from inference import reach

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "fixtures", "reach.json")


@pytest.fixture(scope="module")
def world(db):
    from ui.facts import model
    w = model.load(db)
    db.rollback()
    return w


@pytest.mark.invariant
def test_every_released_hero_is_optimal_on_some_board(world):
    with open(FIXTURE, encoding="utf-8") as handle:
        boards = json.load(handle)
    released = {h.name for h in world.heroes.values() if h.released}
    recorded = {b["hero"] for b in boards}
    assert all(b["bans"] is not None and b["bans"] <= reach.MAX_BANS for b in boards)
    fell = [b["hero"] for b in boards if b["hero"] in released and not reach.seated(world, b)]
    lost = [name for name in sorted((released - recorded) | set(fell))
            if reach.search(world, name)["bans"] is None]
    assert not lost, "no board seats: %s" % ", ".join(lost)
    assert len(fell) <= len(boards) // 5, "the recorded boards have gone stale: %s" % fell
