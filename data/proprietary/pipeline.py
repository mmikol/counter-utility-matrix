"""The proprietary type: what WE judge, authored in the repo.

Nothing here can be re-scraped, so its inputs are committed - the CSVs, the
strategy notes, and the inference layer's own recorded output - and a
rebuild recreates its tables from those files the way it recreates
everything else from the page caches.
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

TYPE = "proprietary"

# The sources row for hand-authored data: there is nothing to fetch, so the
# "url" is the directory the files live in.
USER = ("user", "Hand-authored playbook", "data/proprietary/")

__all__ = ["TYPE", "build_parser", "export_raw", "lookup_ids", "now",
           "prepare_cache", "register_source", "resolve_dsn"]
__all__.append("USER")
