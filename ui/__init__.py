"""The board: the page over the facts layer's facts and the inference
layer's answer. It is the only presentation code, and no layer imports it.

    board.py    the board's server: its settings, its JSON endpoints over
                the facts and the inference layer, and the handler that
                routes to them and to the pages
    pages.py    the board's HTML - the page shell, styled like the game's
                hero select, the math and tests pages - and the static files
                they load
    static/     what the browser loads: the stylesheet, the scripts, the
                display font and its licence, math.html and tests.html
"""
