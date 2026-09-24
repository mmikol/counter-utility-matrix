"""The board a board tool takes: BOARD's five properties - map, red, blue,
bans, side - and board_tool, the decorator that registers a tool over them
and hands its function the one Draft they name. The facts family's facts and
the solver family's infer, evaluate and board are declared through it.
"""

import functools
from collections.abc import Callable, Sequence

from db.mcp.registry import Context, tool
from db.mcp.schema import Properties, ToolReply
from facts.draft import Draft

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
    and the rest of the arguments. The call wears the function's name and
    module, which is its family; the function is returned as it is."""
    def decorate(fn: BoardFn) -> BoardFn:
        call = functools.update_wrapper(functools.partial(_board_call, fn), fn)
        tool(name, description, dict(BOARD, **(properties or {})), required)(call)
        return fn
    return decorate
