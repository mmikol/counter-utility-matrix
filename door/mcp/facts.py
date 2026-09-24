"""The UI layer through the door: the roster - every hero and map the board
tools accept - and a board's facts. Each call loads a World from the
database the context points at, and neither tool writes.
"""

import json
from typing import TypedDict

from door.mcp.boards import board_tool
from door.mcp.registry import Context, tool
from door.mcp.schema import ToolReply
from facts import board_facts, tables
from facts.draft import Draft


class RosterHero(TypedDict):
    """A hero as roster lists it."""
    name: str
    role: str
    subrole: str
    pool: int
    portrait: str | None
    status: str
    release_date: str | None


class RosterMap(TypedDict):
    """A map as roster lists it."""
    name: str
    mode: str | None


@tool(
    "roster", "Every hero with role, subrole, health pool, portrait and status"
    " (released, or announced with its release day - shown, never picked), plus"
    " the map pool with modes - the vocabulary the board tools accept.")
def roster(ctx: Context) -> ToolReply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    heroes = [
        RosterHero(name=h.name, role=h.role, subrole=h.subrole, pool=h.pool,
                   portrait=h.portrait, status=h.status,
                   release_date=str(h.release_date) if h.release_date else None)
        for h in world.heroes_by_role()]
    maps = [RosterMap(name=m.name, mode=m.mode) for m in world.maps_sorted()]
    text = "\n".join("%-9s %-14s %s%s" % (h["role"], h["subrole"], h["name"], _announced(h))
                     for h in heroes) + "\n\nmaps: " + ", ".join(
        "%s (%s)" % (m["name"], m["mode"]) for m in maps)
    return ToolReply(text, {"heroes": heroes, "maps": maps})


def _announced(hero: RosterHero) -> str:
    """What roster's line adds for a hero not yet released: that it is
    announced, and its release day where the wiki gives one."""
    if hero["status"] == "released":
        return ""
    day = hero["release_date"]
    return "  (announced%s)" % (", releases " + day if day else "")


@board_tool(
    "facts", "The UI LAYER: every fact the database holds about a board -"
    " independent facts per named hero and for the map, joint facts per"
    " team once it has picks (shape, effective HP, damage and healing"
    " floors, range, tempo, cohesion, coverage...), and matchup facts"
    " once both teams have picks. Numbered F1.. for citation.",
    {"format": {"type": "string", "enum": ["lines", "json"],
                "description": "lines (default) or json"}})
def facts(ctx: Context, draft: Draft, format: str = "lines") -> ToolReply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    fs = board_facts.generate(world, draft)
    payload = fs.to_dict()
    text = fs.rendered() if format == "lines" else json.dumps(payload)
    return ToolReply(text, payload)
