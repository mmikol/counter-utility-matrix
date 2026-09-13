"""Extracting from the Overwatch Wiki.

    markup  reading the wiki's two markups - Cargo's rendered HTML and article
            wikitext - and the tidying both need

Then one module per domain:

    heroes  ability rows into weapons, abilities and perks
    maps    the Standard Play galleries

The team-composition playstyle lists are a judgement, so their extractor
lives with the heuristic type (data/heuristic/extract/wiki/meta.py).
"""
