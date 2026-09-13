"""The DATA LAYER: pull, clean, store - and the tools that drive it.

    sources/      where pages come from (blizzard, wiki, counterpick), the
                  fetch cache and its freshness policy, and the row each
                  source becomes in the `sources` table
    extract/      markup -> Python, one package per source
    transform/    normalising and deriving values
    load/         storing into Postgres, one module per source and domain,
                  each a run(cx, ...) the MCP tools call; load/authored/
                  stores the inputs we write instead of fetch
    authored/     those inputs: CSVs, strategy notes, recorded transcripts
    mcp/          the MCP server and its tools (the door to this layer)
    orchestrator  the verbs (init, inflate, update, rebuild, export, docs)
    refresh       the daily refresh
    db/           migrations, the ledger, rebuild, restore, generated docs
    common        the plumbing every layer shares

A table is a table: every row carries a source_id, and that is the only
distinction drawn between what was measured, what was judged and what was
written by hand. Any data in the database is just data.
"""
