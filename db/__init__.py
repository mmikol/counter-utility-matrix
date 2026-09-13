"""The DATA LAYER: pull, clean, store - and the tools that drive it.

    data/         the sources, one package each (blizzard, wiki, counterpick,
                  authored), and what they share: the page cache (fetch) and
                  name matching (names). Page to table.
    psql/         the database: where it is and the helpers every writer
                  needs (psql), the schema, the ledger, rebuild, restore
                  and the generated docs (psql.schema), the migrations, and
                  the embedded cluster a local build creates (gitignored)
    mcp/          the MCP server and its tools - the one door to this
                  layer, for a session, the refresher, Docker's entrypoint
                  and the shell (`python -m db.mcp call <tool>`) alike
    refresh       the daily refresh
    raw/          the CSV mirror the tools export (gitignored)

docs/db.md walks the tree. This file holds what the whole layer must
agree on: where things live, and the scope every rates snapshot is pinned
to.

A table is a table: every row carries a source_id, and that is the only
distinction drawn between what was measured, what was judged and what was
written by hand. Any data in the database is just data.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# db/ pairs the schema with what it builds: db/psql/migrations is the source,
# db/psql/cluster the embedded Postgres built from it. The cluster is a build
# artifact - `db_rebuild` reproduces it from the migrations plus the page
# caches - so it is gitignored, not committed.
DEFAULT_DB_DIR = os.path.join(ROOT, "db", "psql", "cluster")
RAW_DIR = os.path.join(ROOT, "db", "raw")
AUTHORED_DIR = os.path.join(ROOT, "db", "db", "data", "authored")

CACHE_DIRS = {
    "blizzard": os.path.join(ROOT, ".cache-blizzard"),
    "wiki": os.path.join(ROOT, ".cache-wiki"),
    "counterpick": os.path.join(ROOT, ".cache-counterpick"),
}

# The scope every rates snapshot is pinned to. The sites spell these their
# own way (Blizzard's input=Console, counterpick's platform=console); these
# are the codes the database stores.
PLATFORM = "console"
INPUT_DEVICE = "controller"
REGION = "americas"
