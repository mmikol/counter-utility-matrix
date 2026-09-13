"""The DATA LAYER: pull, clean, store - and the tools that drive it.

One package per source, each owning the whole path from page to table:
where its pages come from, how they are read, how their values are
normalised, and a run() per domain that stores them - what the MCP tools
call. The tools are the one door; README.md here walks the tree.

    blizzard/     the official site: heroes (roster, roles, portraits,
                  text), meta (rates as dated snapshots)
    wiki/         the MediaWiki endpoint: heroes (kits, numbers, keywords),
                  maps, patches, playstyles - and the markup, measurement,
                  weapon, modifier and name readers the kit data needs
    counterpick/  counterpick.gg: heroes (counters, best maps, its rates)
    playbook      the inputs we write instead of fetch - the CSVs in
                  authored/ - reloaded whole
    sources       the fetch cache, its freshness policy and the project's
                  scope, shared by all
    names         matching hero, map and ability names across sources
    authored/     the CSVs, and the recorded transcripts
    mcp/          the MCP server and its tools - the one door to this
                  layer, for a session, the refresher, Docker's entrypoint
                  and the shell (`python -m data.mcp call <tool>`) alike
    refresh       the daily refresh
    db/           migrations, the ledger, rebuild, restore, generated docs
    common        the plumbing every layer shares

A table is a table: every row carries a source_id, and that is the only
distinction drawn between what was measured, what was judged and what was
written by hand. Any data in the database is just data.
"""
