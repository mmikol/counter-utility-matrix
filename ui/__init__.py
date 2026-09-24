"""The UI LAYER: the board and the facts behind it.

    ui/facts/   the World (the database in memory), the metrics registry,
                and the FactSet - every fact about a map and two teams
    board.py    the board's server: its settings, its JSON endpoints over the
                facts and the inference layer, and the handler that routes to
                them and to the pages
    pages.py    the board's HTML - the page shell, styled like the game's hero
                select, the math and tests pages - and the static files they load
"""
