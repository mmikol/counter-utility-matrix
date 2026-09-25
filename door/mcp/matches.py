"""The owner's recorded matches through the door: record_match, which checks
a played map and stamps the playbook in force before it stores it,
list_matches, newest first, and delete_match, for a map entered wrong. One
record is one map: both sixes - the six on the field longest - the bans,
the map, blue's side and blue's result. Blue is always the owner's team.
The matches are the second input a user writes, beside the playbook, and
carry its `user` source.

A match is checked as the board checks a board, then as only a played map
can be. The names resolve through World.resolve, the board's resolution:
known heroes, released, one seat a team, no banned hero picked. The Draft
refuses a team past six and more than five bans. check_match adds six a
team, at most two tanks a team, and a side given on a sided map and left
empty on any other.
"""

import datetime
from typing import NamedTuple, TypedDict

import psycopg

from db import Refusal, psql
from db import matches as recorded
from db.psql import now, register_source
from door.mcp.registry import Context, tool
from door.mcp.schema import Properties, Property, ToolReply
from facts import tables
from facts.draft import MAX_BANS, SIDES, TEAM_SIZE, Draft, check_tanks, is_sided
from facts.matches import Match, load_matches
from facts.model import Hero, Map, World
from inference import catalog

RESULTS = ("win", "loss", "draw")       # blue's, as matches.result holds them
NOTE_LIMIT = 500                        # characters in a note, once folded onto one line
LISTED = 20                             # the matches list_matches shows unless asked


class MatchRecord(TypedDict):
    """A recorded match as a tool's reply carries it: a Match, the day as
    YYYY-MM-DD."""
    match_id: int
    played_on: str
    map_name: str
    side: str
    result: str
    blue: list[str]
    red: list[str]
    bans: list[str]
    playbook_digest: str
    note: str


def record_of(match: Match) -> MatchRecord:
    """A Match as the replies carry it."""
    return MatchRecord(
        match_id=match.match_id, played_on=match.played_on.isoformat(),
        map_name=match.map_name, side=match.side, result=match.result, blue=list(match.blue),
        red=list(match.red), bans=list(match.bans), playbook_digest=match.playbook_digest,
        note=match.note)


def described(match: Match) -> str:
    """A match in lines: the id, the day, the map, the side and the result,
    then blue's six, red's six, the bans and the note where there are any."""
    head = "#%d  %s  %s  %s%s" % (
        match.match_id, match.played_on.isoformat(), match.map_name,
        match.side + "  " if match.side else "", match.result)
    lines = [head, "  blue  " + ", ".join(match.blue), "  red   " + ", ".join(match.red)]
    if match.bans:
        lines.append("  bans  " + ", ".join(match.bans))
    if match.note:
        lines.append("  note  " + match.note)
    return "\n".join(lines)


# --- the checks ---------------------------------------------------------------

def played_day(value: str | None, today: datetime.date) -> datetime.date:
    """The day a match was played: `value` as YYYY-MM-DD, `today` when there
    is none. A day after tomorrow has not come yet, wherever the caller is."""
    if not value:
        return today
    try:
        day = datetime.date.fromisoformat(value)
    except ValueError:
        raise Refusal("played_on is a day, YYYY-MM-DD, not %r" % value) from None
    if day > today + datetime.timedelta(days=1):
        raise Refusal("played_on %s has not come yet" % day.isoformat())
    return day


def one_line(note: str) -> str:
    """A note folded onto one line, at most NOTE_LIMIT characters."""
    line = " ".join(note.split())
    if len(line) > NOTE_LIMIT:
        raise Refusal("a note is %d characters at most, and this one is %d"
                      % (NOTE_LIMIT, len(line)))
    return line


class CheckedMatch(NamedTuple):
    """A played map once check_match has passed it: the map and each team's
    heroes as the World holds them, in the order named."""
    map: Map
    blue: list[Hero]
    red: list[Hero]
    bans: list[Hero]


def check_match(world: World, draft: Draft) -> CheckedMatch:
    """A played map, checked against the queue and the roster -> its map and
    heroes. The Draft has refused a team past six, more than five bans and a
    side that is not one; the World refuses an unknown or announced hero, a
    hero twice on a team, a banned hero picked and an unknown map. Beyond
    them, each of these is a Refusal: no map, a team short of six, a team of
    three tanks or more, a sided map with no side, and a side on a map that
    has none."""
    resolved = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    played = resolved.map
    if played is None:
        raise Refusal("a recorded match names its map")
    for seat, heroes in (("blue", resolved.blue), ("red", resolved.red)):
        if len(heroes) != TEAM_SIZE:
            raise Refusal("a recorded match holds both sixes, and %s names %d"
                          % (seat, len(heroes)))
        check_tanks(heroes, seat)
    if is_sided(played) and not draft.side:
        raise Refusal("%s has sides: say whether blue attacked or defended" % played.name)
    if not is_sided(played) and draft.side:
        raise Refusal("%s has no sides: leave side empty" % played.name)
    return CheckedMatch(map=played, blue=resolved.blue, red=resolved.red, bans=resolved.banned)


def _require_table(cx: psycopg.Connection) -> None:
    """Refuse a database that predates the matches table: db_migrate adds it
    and keeps the data."""
    if psql.scalar(cx.execute("select to_regclass('matches')")) is None:
        raise Refusal("this database has no matches table yet (migration 024):"
                      " run db_migrate")


# --- the tools ------------------------------------------------------------------

def _heroes(meaning: str) -> Property:
    """An array of hero names (any spelling) meaning what it says."""
    return {"type": "array", "items": {"type": "string"}, "description": meaning}


MATCH: Properties = {
    "map": {"type": "string", "description": "the map played (any spelling)"},
    "side": {
        "type": "string", "enum": [*SIDES, ""],
        "description": "blue's side: attack or defense on an Escort or Hybrid map, empty on"
                       " any other"},
    "result": {"type": "string", "enum": list(RESULTS), "description": "blue's result"},
    "blue": _heroes("blue's six, the owner's team: the six heroes on the field longest"
                    " (any spelling)"),
    "red": _heroes("red's six: the six heroes on the field longest"),
    "bans": _heroes("the match's bans, at most %d; none picked" % MAX_BANS),
    "played_on": {
        "type": "string", "description": "the day it was played, YYYY-MM-DD (default today)"},
    "note": {
        "type": "string",
        "description": "the owner's own line, %d characters at most" % NOTE_LIMIT},
}


@tool(
    "record_match", "Record one map the owner played: the map, blue's side, blue's"
    " result, both sixes (the six on the field longest) and the bans. Blue is always the"
    " owner's team. Checked as the board checks a board - known released heroes, one seat"
    " a team, no banned hero picked, at most five bans - and as only a played map can"
    " be: six a team, at most two tanks a team, the side given on an Escort or Hybrid"
    " map and left empty on any other. Stamped with the digest of the playbook in force"
    " and stored under the user source.", MATCH,
    ["map", "result", "blue", "red"])
def record_match(
        ctx: Context, map: str, result: str, blue: list[str], red: list[str],
        side: str = "", bans: list[str] | None = None, played_on: str | None = None,
        note: str = "") -> ToolReply:
    day = played_day(played_on, datetime.date.today())
    line = one_line(note)
    draft = Draft(map_name=map or None, red=tuple(red), blue=tuple(blue),
                  bans=tuple(bans or ()), side=side)
    with ctx.connect() as cx:
        _require_table(cx)
        checked = check_match(tables.load(cx), draft)
        digest = catalog.playbook_digest()
        cursor = cx.cursor()
        source_id = register_source(cursor, catalog.AUTHORED, now())
        match_id = recorded.store(cursor, recorded.StoredMatch(
            played_on=day, map_id=checked.map.id, side=side, result=result,
            playbook_digest=digest, note=line, blue=tuple(h.id for h in checked.blue),
            red=tuple(h.id for h in checked.red), bans=tuple(h.id for h in checked.bans)),
            source_id)
    match = Match(
        match_id=match_id, played_on=day, map_name=checked.map.name, side=side, result=result,
        blue=tuple(h.name for h in checked.blue), red=tuple(h.name for h in checked.red),
        bans=tuple(h.name for h in checked.bans), playbook_digest=digest, note=line)
    return ToolReply("recorded match %d: %s on %s\n%s" % (
        match_id, result, match.map_name, described(match)), record_of(match))


@tool(
    "list_matches", "The owner's recorded matches, newest first: each map's id, day,"
    " blue's side and result, both sixes, the bans and the note.",
    {"limit": {
        "type": "integer", "description": "how many, 1 or more (default %d)" % LISTED}})
def list_matches(ctx: Context, limit: int = LISTED) -> ToolReply:
    if limit < 1:
        raise Refusal("limit is 1 or more")
    with ctx.connect() as cx:
        every = load_matches(cx)
    newest = every[::-1][:limit]
    if not newest:
        return ToolReply("no matches recorded", {"matches": [], "total": 0})
    text = "%d of %d recorded matches, newest first\n\n%s" % (
        len(newest), len(every), "\n\n".join(described(m) for m in newest))
    return ToolReply(text, {"matches": [record_of(m) for m in newest], "total": len(every)})


@tool(
    "delete_match", "Delete one recorded match by its id, its picks with it: for a map"
    " entered wrong, which is then recorded again. The reply names what went.",
    {"match_id": {"type": "integer", "description": "the id list_matches shows"}},
    ["match_id"])
def delete_match(ctx: Context, match_id: int) -> ToolReply:
    with ctx.connect() as cx:
        found = [m for m in load_matches(cx) if m.match_id == match_id]
        if not found:
            raise Refusal("no recorded match %d" % match_id)
        recorded.delete(cx.cursor(), match_id)
    return ToolReply("deleted match %d\n%s" % (match_id, described(found[0])),
                     {"deleted": record_of(found[0])})
