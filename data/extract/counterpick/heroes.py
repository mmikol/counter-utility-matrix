"""Reading counterpick.gg's hero ranking table.

One row per hero, with eight cells:

    0 hero      3 countered by    6 countered by (repeat)
    1 win %     4 counters        7 best maps
    2 pick %    5 counters (repeat)

Cells 5 and 6 repeat 3 and 4 for a second responsive layout, so they are
ignored.

The site's own field names invert its column labels - the key `counters` is
displayed as "Countered by" - so the tooltips are what settle the direction:
"Countered by" lists heroes to pick *against* this one, and "Counters" lists
heroes to avoid picking against it. They are read that way here, and the two
are kept separately because the site does not treat them as inverses: of 354
pairings, 114 appear in one direction only.
"""

import re

from bs4 import BeautifulSoup

PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")

COUNTERED_BY = 3      # heroes that beat this hero
COUNTERS = 4          # heroes this hero beats
BEST_MAPS = 7


class CounterpickError(Exception):
    pass


def _percent(text):
    match = PERCENT_RE.search(text or "")
    return float(match.group(1)) if match else None


def _alts(cell):
    """The image alt texts in a cell, in order - hero or map names."""
    return [image["alt"].strip() for image in cell.find_all("img")
            if image.get("alt", "").strip()]


def parse_table(html):
    """[{hero, win_rate, pick_rate, countered_by, counters, best_maps}]."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise CounterpickError("no ranking table - the page may have changed")

    heroes = []
    for row in table.select("tbody tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) <= BEST_MAPS:
            continue
        names = _alts(cells[0])
        if not names:
            continue
        heroes.append({
            "hero": names[0],
            "win_rate": _percent(cells[1].get_text(" ", strip=True)),
            "pick_rate": _percent(cells[2].get_text(" ", strip=True)),
            "countered_by": _alts(cells[COUNTERED_BY]),
            "counters": _alts(cells[COUNTERS]),
            "best_maps": _alts(cells[BEST_MAPS]),
        })

    if not heroes:
        raise CounterpickError("ranking table held no hero rows")
    return heroes
