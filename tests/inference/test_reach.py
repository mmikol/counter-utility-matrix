"""Every hero is the right pick somewhere: the playbook may make a hero rare, never
impossible. tests/fixtures/reach.json records, per released hero, the board
inference.reach.search seated it on (a tool: `reach`), within the five bans a match has,
beside the digest of the playbook that seated it; `.venv/bin/python -m scripts.reach`
re-records it.
Rates move daily and the two databases differ, so a few boards may tip; a hero that falls
off its board is searched for again, and none may be lost. The search itself, and the
recorder, run on the synthetic World."""

import json

import pytest

from db import Refusal
from facts.model import World
from inference import catalog, reach
from scripts import reach as recorder
from tests.inference import recorded

UNSEATED = {"Freja", "Shion"}       # named, not waived - see the test


@pytest.mark.invariant
def test_every_hero_reach_finds_a_board_for_is_still_seated_and_none_is_newly_lost(world):
    # reach.json was recorded under the 239 rules 9328429 removed, and names that
    # playbook; a playbook that scores nothing seats heroes by tie-break alone. When
    # rules return this runs again, and a board that no longer seats its hero is
    # searched for anew.
    if not catalog.has_scoring_terms(catalog.load()):
        pytest.skip("the shipped playbook scores nothing: no hero is the right pick")
    fixture = recorded("reach")
    boards = fixture["boards"]
    released = {h.name for h in world.heroes.values() if h.released}
    on_file = {b["hero"] for b in boards}
    assert all(b["bans"] is not None and b["bans"] <= reach.MAX_BANS for b in boards)
    fell = [b["hero"] for b in boards if b["hero"] in released and not reach.seated(world, b)]
    # a stale fixture fails here, before the costly search for what it lost
    stale = (
        "" if fixture["playbook"] == catalog.playbook_digest()
        else " - recorded under a different playbook")
    assert len(fell) <= len(boards) // 5, "the recorded boards have gone stale%s: %s" % (
        stale, fell)
    lost = [name for name in sorted((released - on_file) | set(fell))
            if reach.search(world, name)["bans"] is None]
    # Two heroes reach.search finds no board for. That is not a proof none exists -
    # the search tries four maps and a few reds per hero, so a board it never
    # visits could seat either of them - but it is what the search establishes,
    # and they are named rather than waived: a third joining them fails here.
    # Both were recorded as seated while the reference sample was
    # drawn per ban list - spending a hero's five bans redrew the scale that
    # normalises every heuristic, so the bans flattered the hero as well as
    # clearing its rivals. With the scale held still, Freja reaches 0.34 of the
    # optimum on her best board and Shion 0.40. That is the playbook not valuing
    # what they do, and it is the playbook's to answer.
    newly_lost = set(lost) - UNSEATED
    assert not newly_lost, "no board seats: %s" % ", ".join(sorted(newly_lost))
    seats_again = UNSEATED - set(lost)
    assert not seats_again, ("these seat again - take them out of UNSEATED: %s"
                             % ", ".join(sorted(seats_again)))


def test_the_reach_fixture_names_the_playbook_it_was_recorded_under():
    """Needs no database, so the pull-request gate checks the stamp: the
    fixture names the playbook that seated its heroes and holds one seated
    board per hero."""
    boards = recorded("reach")["boards"]
    heroes = [b["hero"] for b in boards]
    assert len(set(heroes)) == len(heroes), "a hero is recorded twice"
    assert all(b["bans"] is not None for b in boards), "an unseated board is on file"


def test_reach_refuses_a_hero_the_world_does_not_know():
    """A name the World does not hold is the caller's to fix: reach resolves
    its hero the way every board tool does, not a crash inside the search."""
    with pytest.raises(Refusal, match="unknown heroes: Nosuchhero"):
        reach.search(World(), "Nosuchhero")


def test_reach_without_a_map_pool_is_the_servers_fault(synthetic_world, monkeypatch):
    monkeypatch.setattr(reach, "maps", lambda world, hero: [])
    with pytest.raises(RuntimeError, match="no board") as caught:
        reach.search(synthetic_world, "Anvil")
    assert not isinstance(caught.value, Refusal)


def test_a_hero_its_best_map_favours_is_seated_there_with_no_ban(synthetic_world):
    """Anvil's map rates lift it most on Harbor Gate: the search tries that map
    first, finds Anvil in the optimal six against red's likely six, and the
    board it records seats Anvil again when it is solved afresh."""
    anvil = synthetic_world.hero("Anvil")
    assert reach.maps(synthetic_world, anvil)[0].name == "Harbor Gate"
    assert reach.reds(synthetic_world, anvil)[0] == []
    board = reach.search(synthetic_world, "Anvil")
    assert (board["bans"], board["map"], board["red"], board["gap"]) == (0, "Harbor Gate", [], 0.0)
    assert "Anvil" in board["six"] and reach.seated(synthetic_world, board)


class _Connected:
    """psycopg.connect's context manager, connected to nothing."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_recorder_writes_every_seated_hero_beside_the_playbook_digest(
        synthetic_world, monkeypatch, tmp_path, capsys):
    """scripts.reach searches each released hero in name order, records the
    boards that seat one beside the playbook's digest, and names the heroes no
    board seats with the gap each fell short by. The search is stubbed: its
    own tests are above."""
    searched = []

    def search(world, name):
        searched.append(name)
        if name == "Quarry":
            return {"hero": name, "bans": None, "map": "Salt Flats", "side": "", "red": [],
                    "banned": [], "six": [], "gap": 1.235}
        banned = ["Needle"] if name == "Rook" else []
        return {"hero": name, "bans": len(banned), "map": "Harbor Gate", "side": "attack",
                "red": [], "banned": banned, "six": [name], "gap": 0.0}
    monkeypatch.setattr(recorder.psql, "default_dsn", lambda: "postgresql://nowhere")
    monkeypatch.setattr(recorder.psycopg, "connect", lambda dsn: _Connected())
    monkeypatch.setattr(recorder.tables, "load", lambda cx: synthetic_world)
    monkeypatch.setattr(recorder.reach, "search", search)
    monkeypatch.setattr(recorder.catalog, "playbook_digest", lambda: "ab" * 32)
    monkeypatch.setattr(recorder, "OUT", str(tmp_path / "reach.json"))
    assert recorder.main() == 0
    released = sorted(h.name for h in synthetic_world.heroes.values() if h.released)
    assert searched == released and "Wisp" not in searched
    with open(tmp_path / "reach.json", encoding="utf-8") as handle:
        written = json.load(handle)
    assert written["playbook"] == "ab" * 32
    assert [b["hero"] for b in written["boards"]] == [n for n in released if n != "Quarry"]
    assert capsys.readouterr().out == (
        "recorded 11 seated heroes under playbook abababababab, 1 of them after bans;"
        " unseated: Quarry 1.235\n")
