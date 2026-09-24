"""One gate for every door: the same over-limit board sent through the page's
two endpoints, the service's three handlers, the four MCP board tools and
the engine's three entry points is refused with the same message on each.
The synthetic World stands in for the database and the reference playbook
for the live one, every tool call is audited to a scratch file, and every
board solves in this process."""

import contextlib

import pytest

from db import Refusal
from door.mcp import tools
from facts import tables
from facts.draft import Draft
from inference import engine, serve
from tests.inference import FIXTURE_PLAYBOOK
from ui import board as page

SEVEN = ("Balm", "Myrrh", "Sorrel", "Tansy", "Rook", "Needle", "Flint")

# every door that reads a board; the ones that solve apply the queue's tank rule too
FACTS_DOORS = ("page api_facts", "mcp facts")
SOLVING_DOORS = (
    "service handle_infer", "service handle_evaluate", "service handle_board",
    "mcp infer", "mcp evaluate", "mcp board",
    "engine infer", "engine evaluate", "engine board")
DOORS = (*FACTS_DOORS, "page api_board", *SOLVING_DOORS)

OVER_LIMIT = [
    pytest.param({"red": SEVEN, "blue": ("Anvil",)}, "more than 6 red picks", id="seven-red"),
    pytest.param({"blue": SEVEN}, "more than 6 blue picks", id="seven-blue"),
    pytest.param({"blue": ("Anvil",), "bans": SEVEN[:6]}, "more than 5 bans", id="six-bans"),
]


class Offline(tools.Context):
    """The door's context, every tool family registered, over no database:
    tables.load is stubbed."""

    def connect(self, boot=False):
        return contextlib.nullcontext("cx")


@pytest.fixture()
def doors(synthetic_world, monkeypatch, tmp_path):
    """Each door by name, as a call that takes a board: red, blue and bans as
    tuples, one dict for Draft(**board), ctx.call(name, **board) and the HTTP
    doors' parsed query."""
    monkeypatch.setattr(tables, "load", lambda cx: synthetic_world)
    # board() asks the pool for its workers before _board_once refuses
    monkeypatch.setenv("COUNTRIX_PARALLEL", "0")
    monkeypatch.setenv("COUNTRIX_AUDIT", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("COUNTRIX_INFERENCE_URL", raising=False)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    ctx = Offline(dsn="postgresql://nowhere", client="test")

    def query(board):
        return {key: list(value) for key, value in board.items()}

    def tool(name):
        return lambda board: ctx.call(name, **board)

    def solved(entry):
        return lambda board: entry(synthetic_world, Draft(**board), catalog=[])

    return {
        "page api_facts": lambda board: page.api_facts(None, query(board)),
        "page api_board": lambda board: page.api_board(query(board)),
        "service handle_infer": lambda board: serve.handle_infer(None, query(board)),
        "service handle_evaluate": lambda board: serve.handle_evaluate(None, query(board)),
        "service handle_board": lambda board: serve.handle_board(None, query(board)),
        "mcp facts": tool("facts"),
        "mcp infer": tool("infer"),
        "mcp evaluate": tool("evaluate"),
        "mcp board": tool("board"),
        "engine infer": solved(engine.infer),
        "engine evaluate": solved(engine.evaluate),
        "engine board": solved(engine.board),
    }


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize(("board", "message"), OVER_LIMIT)
def test_every_door_refuses_a_board_no_lobby_holds(doors, door, board, message):
    """A seventh pick on either team and a sixth ban: the Draft every door
    builds refuses the board, so no door cuts it or solves it."""
    with pytest.raises(Refusal, match=message):
        doors[door](board)


@pytest.mark.parametrize("door", SOLVING_DOORS)
def test_every_door_that_solves_refuses_a_third_red_tank(doors, door):
    """Three red tanks against one blue pick is refused as the queue's by
    infer, evaluate and board alike, evaluate before it asks for a full six;
    test_engine holds a third blue tank. The facts doors are left out: a
    board's facts state what it holds and apply no tank rule. api_board is
    left out too: past the parse it opens a database connection, and the
    engine board it then solves with is a door here."""
    with pytest.raises(Refusal, match="the queue allows at most 2 tanks, and red picks 3"):
        doors[door]({"red": ("Anvil", "Kite", "Mortar"), "blue": ("Balm",)})
