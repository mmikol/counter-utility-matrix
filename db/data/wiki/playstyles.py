"""Pull + clean + store: overwatch.fandom.com - team composition playstyles.

The playstyles (dive, brawl, poke) and the heroes listed under each. A hero
appears under every playstyle it suits, so the link table is many-to-many
and the lists overlap by design. The page is reloaded wholesale - it is the
whole truth about styles.
"""

import re
from typing import NamedTuple

import psycopg

from db import psql
from db.data import PullSummary, fetch
from db.data.wiki import WIKI, WikiError, fetch_wikitext, markup

# --- extract: markup -> Python ---------------------------------------------

COMPOSITION_PAGE = "Team Composition"

# "=== Dive heroes ===" opens the hero list for the Dive playstyle.
HERO_SECTION_RE = re.compile(r"^===\s*(.+?)\s+heroes\s*===\s*$", re.M | re.I)


class Playstyle(NamedTuple):
    """A playstyle and the heroes the page lists under it, in page order."""
    code: str
    name: str
    heroes: list[str]


def parse_playstyles(text: str) -> list[Playstyle]:
    """[Playstyle(code, name, [hero_name])] in page order."""
    playstyles: list[Playstyle] = []
    for match in HERO_SECTION_RE.finditer(text):
        name = match.group(1).strip()
        body = markup.section_body(text, match.end())
        heroes = [link.strip() for link in markup.LINK_RE.findall(body)]
        if heroes:
            playstyles.append(Playstyle(name.lower(), name, heroes))

    if not playstyles:
        raise WikiError("%s: no '<name> heroes' sections found" % COMPOSITION_PAGE)
    return playstyles


# --- store ---------------------------------------------------------------------

class PlaystylesSummary(PullSummary):
    playstyles: list[str]
    links: int
    unmatched: list[str]


def run(connection: psycopg.Connection, pull: fetch.PullContext) -> PlaystylesSummary:
    """Reload the playstyles and the heroes listed under each -> the styles,
    the hero links stored and the names that matched no hero."""
    playstyles = parse_playstyles(fetch_wikitext(pull.session, COMPOSITION_PAGE, pull.cache_dir))

    cursor = connection.cursor()
    source_id = psql.register_source(cursor, WIKI, psql.now())
    cursor.execute("DELETE FROM playstyle")
    hero_ids = psql.lookup_ids(cursor, "heroes", "name", "hero_id")
    links = 0
    unmatched: list[str] = []
    for code, name, heroes in playstyles:
        for hero_name in heroes:
            hero_id = hero_ids.get(hero_name.lower())
            if hero_id is None:
                unmatched.append("%s: %s" % (name, hero_name))
                continue
            cursor.execute(
                "INSERT INTO playstyle (hero_id, style, source_id)"
                " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (hero_id, code, source_id),
            )
            links += 1
        pull.log("  %-8s %2d heroes" % (name, len(heroes)))
    connection.commit()
    return {"playstyles": [name for _, name, _ in playstyles], "links": links,
            "unmatched": unmatched, "tables": ["playstyle"]}
