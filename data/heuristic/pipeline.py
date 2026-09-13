"""The heuristic type: what a source judges.

Which playstyle a hero belongs to, which hero answers which, where a hero is
strongest. Nobody measures these, so two sources can disagree without either
being wrong. Runs after the authoritative type, whose heroes, maps and
regions it links to.
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

TYPE = "heuristic"

__all__ = ["TYPE", "build_parser", "export_raw", "lookup_ids", "now",
           "prepare_cache", "register_source", "resolve_dsn"]
