"""LOAD: storing into Postgres.

One module per source and domain, each exposing run(cx, cache_dir, ...) -
what the MCP tools call - and a main() for the shell:

    blizzard/     heroes (roster, roles, portraits, text), meta (rates)
    wiki/         heroes (kits, numbers, keywords), maps, patches, playstyles
    counterpick/  heroes (counters, best maps, its own rates)
    authored/     the inputs we write: seasons, strategies, synergies,
                  archetypes, map_playstyle - whole-truth reloads from
                  data/authored/
"""
