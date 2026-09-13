"""Extracting hero rates from Blizzard's statistics page.

The page carries its rows as JSON on a blz-data-table element, and its filter
vocabularies as ordinary select options.
"""

import json

from bs4 import BeautifulSoup


class RatesError(Exception):
    pass


def parse_rows(html):
    """[(hero_name, win_rate, pick_rate, ban_rate)] from the data table JSON."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("blz-data-table")
    if table is None or not table.get("rows"):
        raise RatesError("no blz-data-table rows attribute - the page changed")

    stats = []
    for row in json.loads(table["rows"]):
        cells = row.get("cells", {})
        name = cells.get("name")
        if not name:
            continue
        stats.append(
            (name, cells.get("winrate"), cells.get("pickrate"), cells.get("banrate"))
        )
    if not stats:
        raise RatesError("data table held no hero rows")
    return stats


def parse_filter_options(html, select_id):
    """[(value, label)] for one filter dropdown."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id=select_id)
    if select is None:
        raise RatesError("no %s on the page" % select_id)
    return [
        (option.get("value"), option.get_text(strip=True))
        for option in select.find_all("option")
        if option.get("value")
    ]
