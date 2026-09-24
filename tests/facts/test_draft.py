"""The Draft from facts/draft.py refuses a board no lobby holds wherever it
is built - by a door's parse_board, by the MCP tools' _draft, by the engine's
dataclasses.replace. No database."""

import dataclasses

import pytest

from db import Refusal
from facts.draft import MAX_BANS, TEAM_SIZE, Draft, parse_board

SEVEN = ("Ana", "Kiriko", "Lúcio", "Tracer", "Genji", "Sojourn", "Ashe")


def test_a_draft_refuses_a_team_of_seven_and_a_sixth_ban():
    """Seven picks on a team, or six bans, is no board a lobby holds, and
    cutting either would answer a board the caller did not send: the Draft
    refuses both, whether a door builds it or parses it off the wire."""
    for team in ("red", "blue"):
        with pytest.raises(Refusal, match="more than 6 %s picks" % team):
            Draft(**{team: SEVEN})
        with pytest.raises(Refusal, match="more than 6 %s picks" % team):
            parse_board({team: list(SEVEN)})
    with pytest.raises(Refusal, match="more than 5 bans"):
        Draft(bans=SEVEN[:6])
    with pytest.raises(Refusal, match="more than 5 bans"):
        parse_board({"bans": list(SEVEN[:6])})
    draft = parse_board({"blue": list(SEVEN[:TEAM_SIZE]), "bans": list(SEVEN[:MAX_BANS])})
    assert len(draft.blue) == TEAM_SIZE and len(draft.bans) == MAX_BANS


def test_a_draft_refuses_a_side_that_is_not_one():
    with pytest.raises(Refusal, match="side must be attack or defense, got 'left'"):
        Draft("Harbor Gate", side="left")
    with pytest.raises(Refusal, match="side must be"):
        parse_board({"map": ["Harbor Gate"], "side": ["left"]})
    assert Draft("Harbor Gate", side="attack").side == "attack"


def test_a_replaced_draft_is_checked_again():
    """dataclasses.replace runs the check again, where NamedTuple._replace
    never did, so the engine cannot derive a board past the limits."""
    with pytest.raises(Refusal, match="more than 5 bans"):
        dataclasses.replace(Draft(), bans=SEVEN[:6])
    with pytest.raises(Refusal, match="more than 6 red picks"):
        dataclasses.replace(Draft("Harbor Gate"), red=SEVEN)


def test_parse_board_drops_empty_values():
    draft = parse_board({"map": [""], "red": ["", "Ana"], "blue": [""], "bans": ["", "Ashe"],
                         "side": [""]})
    assert draft == Draft(None, ("Ana",), (), ("Ashe",), "")
