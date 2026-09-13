"""The authoritative type: what a source measured.

Blizzard and the wiki publish facts about the game - a roster, an ability's
cooldown, a hero's health, a map's modes, a win rate. If two sources disagree
here, one of them is wrong. Every stage in this type imports its plumbing
from here (which re-exports data.common), and exposes a `run(cx, ...)` the
data layer's MCP tools call in-process.
"""

from data.common import (  # noqa: F401 - re-exported for the stages
    build_parser,
    export_raw,
    lookup_ids,
    now,
    prepare_cache,
    register_source,
    resolve_dsn,
)

TYPE = "authoritative"

__all__ = ["TYPE", "build_parser", "export_raw", "lookup_ids", "now",
           "prepare_cache", "register_source", "resolve_dsn"]
