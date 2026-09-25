"""The heroes pull's kit pipeline: a hero's kit read from its Cargo rows and
its article, and stored. Nothing here ends in run(); outside the tests,
db/data/wiki/heroes.py, the pull that does, is the one module that imports
it.

    kit_rows        a Cargo Abilities row -> a typed weapon, ability or
                    perk entry of one hero's kit
    hero_articles   a hero's article -> the stats Cargo lacks, the
                    health pool, an announcement
    six_a_side      a hero's article -> its 6v6 kit: the infobox's 6v6
                    pools and each 6v6_details line, a malformed value
                    rejected
    kit_store       the kits into the tables
    measurements    a stat value -> value, unit, window, condition
    weapons         firing modes put in firing order and grouped into
                    weapons
    modifiers       buff direction and target, off the keywords
"""
