"""The door's tools, assembled: importing every family fills REGISTRY, in the
order the server lists them. The servers, the refresher, the shell and the
board import this module for that and for what it re-exports - REGISTRY,
Context, Log, NoSuchToolError and StrategyResources. An in-process call is
ctx.call(name, **arguments).
"""

from db.data.fetch import Log

# each family declares its tools into REGISTRY as it imports
from door.mcp import facts, lifecycle, playbook, pulls, solver  # noqa: F401
from door.mcp.playbook import StrategyResources
from door.mcp.registry import REGISTRY, Context, NoSuchToolError

__all__ = ["REGISTRY", "Context", "Log", "NoSuchToolError", "StrategyResources"]
