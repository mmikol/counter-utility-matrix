"""The DATA LAYER, and the door and the guard that stand over all three layers.

`data/`, `psql/` and `refresh` are the layer itself: pull, clean, store. `mcp/`
and `sentry` sit above it and are the only code here that imports upward - the
door serves the UI layer's facts and the inference layer's solver through the
same tools, and the guard watches the playbook beside the database. The door
gates every write to Postgres and the playbook, the sentry's quarantine rename
aside; the code that writes lives with what it writes, above this layer too:
inference.catalog.mirror reloads the strategies table and inference.tune edits
the playbook's files, each called only from a door tool or from
inference.derive inside a run the door started.

    data/         the sources, one package each (blizzard, wiki; authored
                  names the playbook's source row), and what they
                  share: the page cache (fetch) and name matching (names).
                  Page to table.
    psql/         the database: where it is and the helpers every writer
                  needs (psql), the schema, the ledger, rebuild and the
                  generated docs (psql.schema), the migrations, and the
                  embedded cluster a local build creates (gitignored)
    mcp/          the MCP server and its tools - the one door to all three
                  layers, for a session, the refresher, Docker's entrypoint
                  and the shell (`python -m db.mcp call <tool>`) alike. It
                  gates every write and every pull; a read goes straight to
                  Postgres over db.psql.default_dsn()
    refresh       the daily refresh
    sentry        the guard: the playbook, the free text in the database, the door
    web           what the three HTTP servers share: the Host-and-Origin
                  guard, the handler that sends and logs, the reply to a
                  request that raised (a Refusal 400, anything else 500 with
                  its traceback on stderr), and the one MCP client
    raw/          the CSV mirror the tools export (gitignored)

This file holds what the whole layer must agree on: where things live (ROOT
and the paths under it), the shape of a `sources` row (Source), the ability
and perk vocabularies the migrations seed (ABILITY_KINDS, PERK_TIERS), the
scope every rates snapshot is pinned to, the one error a caller can fix
(Refusal), which every layer raises and every door answers as the caller's,
and embed, which rewrites one generated section of a markdown file for every
layer that generates docs.
docs/db.md walks the tree.

Every row carries a source_id, and that is the only distinction drawn
between what was measured, what was judged and what was written by hand.
Only the strategies are written by hand: no other table carries the `user`
source.
"""

import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# db/ pairs the schema with what it builds: db/psql/migrations is the source,
# db/psql/cluster the embedded Postgres built from it. The cluster is a build
# artifact - `db_rebuild` reproduces it from the migrations plus the page
# caches - so it is gitignored, not committed.
DEFAULT_DB_DIR = os.path.join(ROOT, "db", "psql", "cluster")
RAW_DIR = os.path.join(ROOT, "db", "raw")

CACHE_DIRS = {
    "blizzard": os.path.join(ROOT, ".cache-blizzard"),
    "wiki": os.path.join(ROOT, ".cache-wiki"),
}


class Refusal(ValueError):  # noqa: N818  # named for the answer every door gives it
    """A request the caller can fix: a name, a value or a board the caller can
    change. Every door answers it as the caller's error; anything else is the
    server's fault."""


@dataclass(frozen=True)
class Source:
    """A `sources` row: the code every row a source's pages become carries
    (through its source_id), its name, and where it is read from."""
    code: str
    name: str
    url: str


# The ability vocabulary: db/psql/migrations/002_heroes.sql seeds ability_kinds
# with these codes, db/data/wiki/kit_store.py resolves each to its kind_id when
# it writes, and the UI layer's facts package compares kits against them.
KIND_WEAPON, KIND_ABILITY, KIND_ULTIMATE, KIND_PASSIVE = (
    "weapon", "ability", "ultimate", "passive")
ABILITY_KINDS = (KIND_WEAPON, KIND_ABILITY, KIND_ULTIMATE, KIND_PASSIVE)

# The perk tiers: the ids 002_heroes.sql seeds into perk_tiers (1 minor, 2
# major). Blizzard's pages and the wiki's rows both name a perk's tier by code.
PERK_TIERS = {"minor": 1, "major": 2}

# The scope every rates snapshot is pinned to. Blizzard spells these its own
# way (input=Console); these are the codes the database stores.
PLATFORM = "console"
INPUT_DEVICE = "controller"
REGION = "americas"


def embed(path: str, name: str, text: str) -> None:
    """Replace the generated section `name` of a markdown file - the text between
    <!-- generated:name --> and <!-- /generated:name --> - keeping the rest. A
    file without both markers is a ValueError."""
    with open(path, encoding="utf-8") as handle:
        doc = handle.read()
    start, end = "<!-- generated:%s -->" % name, "<!-- /generated:%s -->" % name
    if start not in doc or end not in doc:
        raise ValueError("%s has no %s markers" % (path, name))
    head = doc[:doc.index(start) + len(start)]
    tail = doc[doc.index(end):]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(head + "\n" + text.strip("\n") + "\n" + tail)
