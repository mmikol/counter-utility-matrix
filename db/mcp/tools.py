"""The door's tools, assembled: every family's tools in one registry, in the
order the server lists them, and the context a call lands in.

    registry     what a tool is (ToolSpec, ToolReply), the Registry a family
                 declares its tools into, and the Context base
    pulls        pull, clean, store: list_sources, the ten pull_* tools in
                 dependency order, load_authored, sync_all
    lifecycle    the database's life: db_status, db_init, db_migrate,
                 db_rebuild, export_csv, db_docs, and read-only query
    layers       the UI and inference layers through the same door: roster,
                 facts, infer, evaluate, reach, board, metrics
    playbook     the playbook: strategies, tune, add_strategy,
                 infer_strategy, derive_strategies, tuning_log, and the
                 strategy:// resources

No family imports another or this module: a tool reaches another tool
through its context (ctx.call, ctx.tools), which carries the joined
registry, so nothing depends on the order the families import in. This
module joins them in the order above; the servers, the refresher, the board
and the shell read it.
"""

from db.data.fetch import Log
from db.mcp import layers, lifecycle, playbook, pulls, registry
from db.mcp.playbook import StrategyResources
from db.mcp.registry import NoSuchToolError, Registry, ToolReply
from db.mcp.server import Tool

__all__ = [
    "REGISTRY", "Context", "Log", "NoSuchToolError", "StrategyResources", "build", "run_tool",
    "write_tool_docs"]

REGISTRY = Registry.joined(pulls.TOOLS, lifecycle.TOOLS, layers.TOOLS, playbook.TOOLS)


class Context(registry.Context):
    """Where a tool call lands, with every family's tools to reach."""
    tools = REGISTRY


def build(ctx: Context) -> list[Tool]:
    """Bind every tool to a context, for a server to serve -> [Tool]."""
    return REGISTRY.bind(ctx)


def run_tool(ctx: Context, name: str, /, **arguments: object) -> ToolReply:
    """Call a tool by name, in-process - the refresher's, the shell's and the
    board's path - validated and audited like a call through either door
    (Registry.run)."""
    return REGISTRY.run(ctx, name, **arguments)


def write_tool_docs(path: str | None = None) -> str:
    """The tool reference, generated into docs/mcp.md -> the path written."""
    return REGISTRY.write_docs(path)
