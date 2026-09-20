"""The DATA LAYER: pull, clean, store - and the tools that drive it.

    data/         the sources, one package each (blizzard, wiki; authored
                  names the playbook's source row), and what they
                  share: the page cache (fetch) and name matching (names).
                  Page to table.
    psql/         the database: where it is and the helpers every writer
                  needs (psql), the schema, the ledger, rebuild and the
                  generated docs (psql.schema), the migrations, and the
                  embedded cluster a local build creates (gitignored)
    mcp/          the MCP server and its tools - the one door to this
                  layer, for a session, the refresher, Docker's entrypoint
                  and the shell (`python -m db.mcp call <tool>`) alike
    refresh       the daily refresh
    sentry        the guard: the playbook, the free text in the database, the door
    raw/          the CSV mirror the tools export (gitignored)

This file holds what the whole layer must agree on: where things live, and
the scope every rates snapshot is pinned to. docs/db.md walks the tree.

Every row carries a source_id, and that is the only distinction drawn
between what was measured, what was judged and what was written by hand.
Only the strategies are written by hand: no other table carries the `user`
source.
"""

import os

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

# The scope every rates snapshot is pinned to. Blizzard spells these its own
# way (input=Console); these are the codes the database stores.
PLATFORM = "console"
INPUT_DEVICE = "controller"
REGION = "americas"
