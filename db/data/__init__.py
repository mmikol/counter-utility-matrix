"""The sources: one package per source, each owning the whole path from
page to table, plus what they share.

    blizzard/     the official site: heroes (roster, roles, portraits,
                  text), meta (rates as dated snapshots)
    wiki/         the MediaWiki endpoint: heroes (kits, numbers, keywords),
                  maps, patches, playstyles - and the markup, measurement,
                  weapon and modifier readers the kit data needs
    counterpick/  counterpick.gg: heroes (counters, best maps, its rates)
    authored/     the inputs we write instead of fetch - the CSVs and the
                  loader that reloads them whole
    fetch         the page cache and its freshness policy
    names         matching hero, map and ability names across sources

Each fetched source's domain module ends in a
run(connection, cache_dir, session, log); authored/ ends in its LOADERS.
The MCP tools call them. Nothing here is an entry point of its own.
"""
