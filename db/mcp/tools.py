"""The door's tools, assembled: every family imported, so the one registry
holds every tool, in the order the server lists them, and the in-process
call the refresher, the shell and the board make.

    registry     a tool as registered (ToolSpec), the one Registry every
                 family declares its tools into, the order it lists the
                 families in (FAMILIES), and the Context a call lands in
    pulls        pull, clean, store: list_sources, the ten pull_* tools in
                 dependency order, load_authored, sync_all
    lifecycle    the database's life: db_status, db_init, db_migrate,
                 db_rebuild, export_csv, db_docs, and read-only query
    facts        the UI layer: roster and a board's facts
    solver       the inference layer: infer, evaluate, reach and board
    playbook     the playbook: metrics, strategies, tune, add_strategy,
                 infer_strategy, derive_strategies, tuning_log, and the
                 strategy:// resources

No family imports another or this module: a tool reaches another tool
through its context (ctx.call, ctx.tools), which carries the one registry,
and the registry lists the families in FAMILIES' order whichever imports
first. This module imports them all, so the registry is whole wherever it
is read from here; the servers, the refresher, the board and the shell read
it.
"""

from db.data.fetch import Log

# each family declares its tools into REGISTRY as it imports
from db.mcp import facts, lifecycle, playbook, pulls, solver  # noqa: F401
from db.mcp.playbook import StrategyResources
from db.mcp.registry import REGISTRY, Context, NoSuchToolError
from db.mcp.schema import Tool, ToolReply

__all__ = [
    "REGISTRY", "Context", "Log", "NoSuchToolError", "StrategyResources", "build", "run_tool",
    "write_tool_docs"]


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
