"""EXTRACT: pulling structured data out of fetched markup.

One package per source, because the markup differs:

    blizzard/     page HTML - the roster, hero pages, the rates table
    wiki/         Cargo's rendered values and article wikitext - kits, maps,
                  patches, the team-composition playstyles
    counterpick/  its server-rendered ranking table

Nothing here touches the network or the database. What comes out is source
data in Python form; normalising it is the transform stage.
"""
