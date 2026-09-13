"""The DATA LAYER: pull, clean, store - and the tools that drive it.

One package per source, each owning the whole path from page to table:
where its pages come from, how they are read, how their values are
normalised, and a run() per domain that stores them - what the MCP tools
call. The tools are the one door; README.md here walks the tree.

    blizzard/     the official site: heroes (roster, roles, portraits,
                  text), meta (rates as dated snapshots)
    wiki/         the MediaWiki endpoint: heroes (kits, numbers, keywords),
                  maps, patches, playstyles - and the markup, measurement,
                  weapon, modifier readers the kit data needs
    counterpick/  counterpick.gg: heroes (counters, best maps, its rates)
    authored/     the inputs we write instead of fetch - the CSVs and the
                  loader that reloads them whole, the recorded transcripts
    fetch         the page cache and its freshness policy, shared by all
    names         matching hero, map and ability names across sources
    db/           the database: where it is and the helpers every writer
                  needs (db), the schema, the ledger, rebuild, restore,
                  the generated docs (db.schema), the migrations
    mcp/          the MCP server and its tools - the one door to this
                  layer, for a session, the refresher, Docker's entrypoint
                  and the shell (`python -m data.mcp call <tool>`) alike
    refresh       the daily refresh

This file holds what the whole layer must agree on: where things live,
and the scope every rates snapshot is pinned to.

A table is a table: every row carries a source_id, and that is the only
distinction drawn between what was measured, what was judged and what was
written by hand. Any data in the database is just data.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# db/ pairs the schema with what it builds: data/db/migrations is the source,
# data/db/cluster the embedded Postgres built from it. The cluster is a build
# artifact - `db_rebuild` reproduces it from the migrations plus the page
# caches - so it is gitignored, not committed.
DEFAULT_DB_DIR = os.path.join(ROOT, "data", "db", "cluster")
RAW_DIR = os.path.join(ROOT, "data", "raw")
AUTHORED_DIR = os.path.join(ROOT, "data", "authored")

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
