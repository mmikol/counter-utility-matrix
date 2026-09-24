"""The UI LAYER: the board and the facts behind it.

Two things share this package. facts/ is not presentation: it is the FACTS
kernel - the World, the metrics registry, the FactSet - that inference/,
db/mcp and scripts/reach.py import, so the solver, the deriver and the door
all read the numbers the board shows. board.py, pages.py and static/ are
the only presentation code, and no other layer imports them.

    facts/      the World (the database in memory), the metrics registry,
                and the FactSet - every fact about a map and two teams
    board.py    the board's server: its settings, its JSON endpoints over
                the facts and the inference layer, and the handler that
                routes to them and to the pages
    pages.py    the board's HTML - the page shell, styled like the game's
                hero select, the math and tests pages - and the static files
                they load
    static/     what the browser loads: the stylesheet, the scripts, the
                display font and its licence, math.html and tests.html
"""
