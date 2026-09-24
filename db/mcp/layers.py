"""The UI and inference layers through the same door: the roster, a board's
facts, the solver's infer, evaluate, reach and board, and the metric
vocabulary a strategy may reference.

The four board tools - facts, infer, evaluate, board - share BOARD's five
properties and are registered through board_tool, which hands each function
the one Draft they name. Each call loads a World from the database the
context points at, and none of these tools writes. This module is where
the door imports ui/facts and the solver.
"""

import functools
import json
from collections.abc import Callable, Mapping, Sequence
from typing import TypedDict

from db.mcp.registry import Context, Registry
from db.mcp.schema import Properties, ToolReply
from inference import catalog, engine, reach
from inference.result import Result
from ui.facts import board_facts, compute, tables
from ui.facts.draft import Draft

TOOLS = Registry()
tool = TOOLS.tool

BOARD: Properties = {
    "map": {"type": "string", "description": "map name (any spelling)"},
    "red": {
        "type": "array", "items": {"type": "string"},
        "description": "the enemy team's revealed heroes"},
    "blue": {
        "type": "array", "items": {"type": "string"},
        "description": "your team's locked heroes"},
    "bans": {
        "type": "array", "items": {"type": "string"},
        "description": "the match's bans, up to five (each team's two and"
                       " the lobby's), all optional; neither team can"
                       " pick them"},
    "side": {
        "type": "string", "enum": ["attack", "defense", ""],
        "description": "blue's side on an Escort or Hybrid map (red gets"
                       " the other); ignored on Control, Push, Flashpoint"},
}

# A board tool's function: its context, the Draft, then its own arguments.
type BoardFn = Callable[..., ToolReply]


def _names(value: object) -> tuple[str, ...]:
    """An array of names the schema admitted, as the tuple a Draft holds."""
    return tuple(str(v) for v in value) if isinstance(value, (list, tuple)) else ()


def _draft(arguments: dict[str, object]) -> Draft:
    """The board BOARD's five arguments name, taken out of the call's
    arguments: the lists as tuples, and what the call left out empty."""
    map_name = arguments.pop("map", None)
    return Draft(map_name=None if map_name is None else str(map_name),
                 red=_names(arguments.pop("red", ())),
                 blue=_names(arguments.pop("blue", ())),
                 bans=_names(arguments.pop("bans", ())),
                 side=str(arguments.pop("side", "")))


def _board_call(fn: BoardFn, ctx: Context, /, **arguments: object) -> ToolReply:
    """A board tool's call: its function handed the one Draft BOARD's
    arguments name, then the rest of them."""
    return fn(ctx, _draft(arguments), **arguments)


def board_tool(
        name: str, description: str, properties: Properties | None = None,
        required: Sequence[str] = ()) -> Callable[[BoardFn], BoardFn]:
    """The decorator that registers a board tool: BOARD's five properties
    first, then its own, and the function called with the one Draft they name
    and the rest of the arguments. The function is returned as it is."""
    def decorate(fn: BoardFn) -> BoardFn:
        tool(name, description, dict(BOARD, **(properties or {})), required)(
            functools.partial(_board_call, fn))
        return fn
    return decorate


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


COMPACT_TERMS = 15        # the heaviest terms a compact reply carries


class WeightedTerm(TypedDict):
    """One scoring term of a compact reply: its strategy and its weighted part
    of the score."""
    id: str
    weighted: float


class CompactInfer(TypedDict):
    """A compact infer reply's payload: the board and the six with its score;
    how many scoring terms the full reply's contributions carry (terms), how
    many of them do not apply here (idle), the applying heuristics whose
    metric does not vary on this board (silent), and the heaviest terms."""
    map: str | None
    side: str
    red: list[str]
    blue: list[str]
    score: float
    terms: int
    idle: int
    silent: list[str]
    largest: list[WeightedTerm]


@board_tool(
    "infer", "The INFERENCE LAYER: the optimal six for this board under"
    " the markdown strategies in inference/strategies/ (players assumed"
    " to play optimally). Locked blue picks are kept; the rest is"
    " searched. Returns the comp, per-pick reasons with fact citations,"
    " the strategy score breakdown, and alternatives.",
    {
        "top": {"type": "integer", "description": "alternatives to return (default 5)"},
        "pool": {"type": "integer",
                 "description": "candidates per role the search keeps (default 6)"},
        "compact": {"type": "boolean",
                    "description": "true: a reply small enough to carry under a"
                                   " playbook of hundreds. The structured payload"
                                   " then has its own keys: map, side, red, blue,"
                                   " score, terms (how many scoring terms the full"
                                   " reply carries), idle, silent (applying,"
                                   " metric not varying on this board) and largest"
                                   " (the %d heaviest terms, each an id and its"
                                   " weighted value)" % COMPACT_TERMS}})
def infer(
        ctx: Context, draft: Draft, top: int = 5, pool: int = 6,
        compact: bool = False) -> ToolReply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    pool, top = engine.clamp_search(pool, top)
    result = engine.infer(world, draft, pool_size=pool, top=top)
    if compact:
        return ToolReply(*_compact(result))
    return ToolReply(result.rendered(), result.to_dict())


def _compact(result: Result) -> tuple[str, CompactInfer]:
    """A result small enough for a tool reply under a playbook of hundreds:
    the comp, the heuristics that apply but whose metric does not vary on this
    board, and the largest terms."""
    terms = result.contributions
    silent = sorted(c["id"] for c in terms if c.get("spread") is False)   # applying heuristics
    idle = sum(1 for c in terms if not c["applies"])
    largest = sorted((c for c in terms if c["weighted"]),
                     key=lambda c: (-abs(c["weighted"]), c["id"]))[:COMPACT_TERMS]
    payload = CompactInfer(
        map=result.map_name, side=result.side, red=list(result.red), blue=list(result.blue),
        score=round(result.score, 3), terms=len(terms), idle=idle, silent=silent,
        largest=[WeightedTerm(id=c["id"], weighted=round(c["weighted"], 4)) for c in largest])
    lines = result.rendered().split("\n")[:2]
    lines.append("  %d terms, %d not applying here" % (len(terms), idle))
    lines.append("  silent (applies, metric does not vary here): %s"
                 % (", ".join(silent) or "none"))
    lines += ["  %+.2f  %s" % (c["weighted"], c["id"]) for c in largest]
    return "\n".join(lines), payload


@board_tool(
    "evaluate", "Score a FULL blue six against the strategies without"
    " searching: the breakdown per strategy, constraint violations, and"
    " how it ranks against the optimum.", required=["blue"])
def evaluate(ctx: Context, draft: Draft) -> ToolReply:
    # the schema requires blue: the engine takes a full six, so a call
    # without one never reaches the engine
    with ctx.connect() as cx:
        world = tables.load(cx)
    result = engine.evaluate(world, draft)
    return ToolReply(result.rendered(), result.to_dict())


@tool(
    "reach", "Can the playbook ever pick this hero? A board that suits it - one of"
    " its maps, a red it answers, the match's bans spent on the rivals holding its seat - on"
    " which it is in the optimal six; with none, the closest it came. A hero that"
    " cannot be reached is one the facts or the strategies cannot see.",
    {"hero": {"type": "string", "description": "a released hero (any spelling)"}},
    ["hero"])
def reach_tool(ctx: Context, hero: str) -> ToolReply:   # _tool: inference.reach holds the bare name
    with ctx.connect() as cx:
        world = tables.load(cx)
    found = reach.search(world, hero)
    where = "%s%s against %s" % (found["map"], " " + found["side"] if found["side"] else "",
                                 ", ".join(found["red"]) or "the likely six")
    if found["bans"] is None:
        return ToolReply("%s is never the optimal pick, even with every ban; closest on %s,"
                         " %.2f behind" % (found["hero"], where, found["gap"]), found)
    return ToolReply("%s is optimal on %s%s: %s" % (
        found["hero"], where,
        ", with %s banned" % ", ".join(found["banned"]) if found["banned"] else "",
        ", ".join(found["six"])), found)


@board_tool(
    "board", "The whole board at any stage of the draft (no map, a map, a side,"
    " bans, red's picks as they reveal): blue's optimal six as the best counter"
    " to red's selection - to their likely six until they reveal a pick"
    " (blue's own picks never constrain it), red's best"
    " counter to yours, both current comps scored on those scales, your picks"
    " against red's best counter, your locked picks with the empty slots filled,"
    " the fight odds (each seat's share of its own optimal, and the two against"
    " each other), the game plan in prose, the shapes the queue and the"
    " playbook's limits allow, and red's likely six"
    " from the data alone (a two-two-two from the map's pick rates and the"
    " wiki's synergies, past the bans; static for the board, no strategy read).",
    {
        "pool": {"type": "integer",
                 "description": "candidates per role the search keeps (default 6)"},
        "weights": {"type": "object",
                    "description": "{heuristic id: 0..10} - weights to score this"
                                   " board under instead of the files' (the playbook"
                                   " tab's sliders); the files are untouched"}})
def board(
        ctx: Context, draft: Draft, pool: int = 6,
        weights: Mapping[str, object] | None = None) -> ToolReply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    pool, _ = engine.clamp_search(pool)
    brief = engine.Brief(pool_size=pool, weights=catalog.parse_weights(weights or {}))
    b = engine.board(world, draft, brief=brief)
    return ToolReply(b.rendered(), b.to_dict())


@tool(
    "metrics", "The vocabulary a strategy may reference: every metric key with its"
    " meaning - team.*, enemy.* (the same for the red side), matchup.*, map.*,"
    " world.* - and which are text. What /strategy reads to infer a heuristic's"
    " metric or a constraint's expression from prose.")
def metrics(ctx: Context) -> ToolReply:
    reg = compute.registry()
    numeric = {k: v for k, v in reg.items() if k not in compute.TEXT_METRICS}
    lines = [
        "%-32s %s%s" % (k, v, "  (text)" if k in compute.TEXT_METRICS else "")
        for k, v in reg.items() if not k.startswith("enemy.")]
    return ToolReply("\n".join(lines), {"metrics": reg, "numeric": sorted(numeric),
                                        "text": sorted(compute.TEXT_METRICS)})
