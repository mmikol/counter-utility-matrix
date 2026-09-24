"""The inference layer through the door: the solver's infer, evaluate, reach
and board. infer, evaluate and board are board tools (boards.board_tool);
reach takes a hero. Each call loads a World from the database the context
points at, and none of these tools writes.
"""

from collections.abc import Mapping
from typing import TypedDict

from door.mcp.boards import board_tool
from door.mcp.registry import Context, tool
from door.mcp.schema import Property, ToolReply
from facts import tables
from facts.draft import Draft
from inference import catalog, engine, reach
from inference.result import Result

COMPACT_TERMS = 15        # the heaviest terms a compact reply carries

# the search knobs as the tools describe them; clamp_search holds their rule
TOP: Property = {
    "type": "integer",
    "description": "alternatives to return, 1 to %d (default %d)"
                   % (engine.TOP_CEILING, engine.TOP_DEFAULT)}
POOL: Property = {
    "type": "integer",
    "description": "candidates per role the search keeps, 2 to %d (default %d)"
                   % (engine.POOL_CEILING, engine.POOL_DEFAULT)}


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
        "top": TOP,
        "pool": POOL,
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
        ctx: Context, draft: Draft, top: int | None = None, pool: int | None = None,
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
    if not found["seated"]:
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
        "pool": POOL,
        "weights": {"type": "object",
                    "description": "{heuristic id: 0..10} - weights to score this"
                                   " board under instead of the files' (the playbook"
                                   " tab's sliders); the files are untouched"}})
def board(
        ctx: Context, draft: Draft, pool: int | None = None,
        weights: Mapping[str, object] | None = None) -> ToolReply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    pool, _ = engine.clamp_search(pool)
    brief = engine.Brief(pool_size=pool, weights=catalog.parse_weights(weights or {}))
    b = engine.board(world, draft, brief=brief)
    return ToolReply(b.rendered(), b.to_dict())
