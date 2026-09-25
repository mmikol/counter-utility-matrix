"""The facts layer through the door: the roster - every hero and map the
board tools accept - and a board's facts. Each call loads a World from the
database the context points at, and neither tool writes.
"""

import json

from door.mcp.boards import board_tool
from door.mcp.registry import Context, tool
from door.mcp.schema import ToolReply
from facts import board_facts, tables
from facts.draft import Draft
from facts.roster import RosterHero, RosterMap, roster_of


@tool(
    "roster", "Every hero with role, subrole, health pool, portrait and status"
    " (released, or announced with its release day - shown, never picked), plus"
    " the map pool with each map's mode, the style it rewards most and whether it"
    " has an attacking and a defending side - the vocabulary the board tools accept.")
def roster(ctx: Context) -> ToolReply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    listed = roster_of(world)
    text = "\n".join("%-9s %-14s %s%s" % (h["role"], h["subrole"], h["name"], _announced(h))
                     for h in listed["heroes"]) + "\n\nmaps: " + ", ".join(
        _described(m) for m in listed["maps"])
    return ToolReply(text, listed)


def _announced(hero: RosterHero) -> str:
    """What roster's line adds for a hero not yet released: that it is
    announced, and its release day where the wiki gives one."""
    if hero["status"] == "released":
        return ""
    day = hero["release_date"]
    return "  (announced%s)" % (", releases " + day if day else "")


def _described(m: RosterMap) -> str:
    """A map as roster's text lists it: the name, then in parentheses its
    mode, the style it rewards most and "sided" when it has an attacking and
    a defending side, each only where the map has one."""
    parts = [x for x in (m["mode"], m["style"], "sided" if m["sided"] else None) if x]
    return "%s (%s)" % (m["name"], ", ".join(parts)) if parts else m["name"]


@board_tool(
    "facts", "The FACTS LAYER: every fact the database holds about a board -"
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
