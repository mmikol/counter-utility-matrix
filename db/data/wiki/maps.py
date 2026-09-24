"""Pull + clean + store: overwatch.fandom.com - maps, game modes, stages.

Only the Maps article's "Standard Play" section is read; Former Standard
Play (Assault, Clash), Stadium, Arcade, Custom Games, Training and seasonal
modes are out of scope. Each map's own article supplies its stages; the
Hybrid article supplies the two phases every Hybrid map plays.
"""

import re
from collections.abc import Sequence
from typing import NamedTuple

import psycopg

from db import psql
from db.data import ArticlePullSummary, fetch
from db.data.wiki import WIKI, WikiError, fetch_articles, fetch_wikitext, markup

# --- extract: markup -> Python ---------------------------------------------

# The competitive rotation lives between these two headings.
SECTION_START = "== Standard Play =="
SECTION_END = "== Former Standard Play =="

# <gallery class="maps-gallery maps-gallery--control"> ... </gallery>
GALLERY_RE = re.compile(
    r"<gallery[^>]*maps-gallery--([a-z]+)[^>]*>(.*?)</gallery>", re.S | re.I
)
# File:Busan.jpg|{{flag|kr}} [[Busan]]
MAP_LINE_RE = re.compile(r"^File:[^|]*\|(.*)$", re.M)

MODE_NAMES = {
    "control": "Control",
    "escort": "Escort",
    "flashpoint": "Flashpoint",
    "hybrid": "Hybrid",
    "push": "Push",
}


def standard_play_section(text: str) -> str:
    """Just the Standard Play part of the article."""
    try:
        start = text.index(SECTION_START)
    except ValueError:
        raise WikiError("Maps: no %r heading" % SECTION_START) from None
    end = text.find(SECTION_END, start)
    return text[start:end if end != -1 else len(text)]


class Mode(NamedTuple):
    """A game mode of the Standard Play rotation and its maps, in page order."""
    code: str
    name: str
    maps: list[str]


def parse_modes_and_maps(text: str) -> list[Mode]:
    """[Mode(mode_code, mode_name, [map_name])] in page order."""
    section = standard_play_section(text)
    modes: list[Mode] = []
    for match in GALLERY_RE.finditer(section):
        code = match.group(1).lower()
        if code not in MODE_NAMES:
            continue

        maps: list[str] = []
        for line in MAP_LINE_RE.findall(match.group(2)):
            link = markup.LINK_RE.search(line)
            if link:
                maps.append(link.group(1).strip())

        modes.append(Mode(code=code, name=MODE_NAMES[code], maps=maps))

    if not modes:
        raise WikiError("Maps: no mode galleries found in Standard Play")
    return modes


# --- stages ------------------------------------------------------------------
#
# Control and Flashpoint maps: the submaps, from the Gameplay section's list.
# Escort maps: the stretches of the route, where the article names them.
# Hybrid maps: the two phases the Hybrid article names. Push maps: none.

GAMEPLAY_SECTION_RE = re.compile(
    r'^==\s*Gameplay\s*==\s*$(.*?)(?=^==|\Z)', re.M | re.S)
# The same section with its === subsections ===, cut at the next == heading.
GAMEPLAY_WHOLE_RE = re.compile(
    r'^==\s*Gameplay\s*==\s*$(.*?)(?=^==[^=]|\Z)', re.M | re.S)
SUBHEADING_RE = re.compile(r'^===\s*([^=].*?)\s*===\s*$', re.M)
LINK_TEXT_RE = re.compile(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]')
LEADING_ARTICLE_RE = re.compile(r'^(?:the|an?)\s+', re.I)

HYBRID_PAGE = "Hybrid"
# "It is a combination of the [[Assault]] and [[Escort]] modes."
PHASES_RE = re.compile(
    r'combination of\s+(?:the\s+)?(\[\[[^\]]+\]\])\s+and\s+'
    r'(?:the\s+)?(\[\[[^\]]+\]\])', re.I)


def parse_stages(text: str) -> list[str]:
    """[stage name, ...] in article order, or [] when the map has none.

    Control and Flashpoint maps list their submaps as the top-level bullets
    of the Gameplay section (descriptions sit under them as ** sub-bullets,
    thumbnails between them). The section is cut at the first heading of any
    depth so a === Stadium === subsection cannot leak its maps in. Escort,
    Hybrid and Push maps describe their route in prose, no bullets - an empty
    result is normal there, not a parse failure.
    """
    section = GAMEPLAY_SECTION_RE.search(text)
    if not section:
        return []
    body = section.group(1)
    stages: list[str] = []
    for line in body.splitlines():
        if not line.startswith('*') or line.startswith('**'):
            continue
        name = LINK_TEXT_RE.sub(r'\1', line.lstrip('* ').strip())
        name = re.sub(r'\s*\([A-Z]\)\s*$', '', name).strip("'\" ")
        if name and len(name) <= 40 and '. ' not in name:
            stages.append(name)
    return stages if len(stages) >= 2 else []


def parse_stretches(text: str) -> list[str]:
    """[stretch name, ...] in route order, or [] when the article names none.

    An article that names its route opens the Gameplay section with the list
    ("takes place in three main locations: The City Streets, the Distillery,
    and the Sea Fort") and gives each a === subsection ===. A subsection is a
    stretch when that opening names it, a leading article aside: Rialto's
    === Gondola Rides === is not one.
    """
    section = GAMEPLAY_WHOLE_RE.search(text)
    if not section:
        return []
    body = section.group(1)
    first = SUBHEADING_RE.search(body)
    if not first:
        return []
    opening = markup.wikitext_to_text(body[:first.start()]).casefold()
    stretches: list[str] = []
    for heading in SUBHEADING_RE.findall(body):
        name = markup.wikitext_to_text(heading)
        if LEADING_ARTICLE_RE.sub("", name).casefold() in opening:
            stretches.append(name)
    return stretches if len(stretches) >= 2 else []


def parse_phases(text: str) -> list[str]:
    """The Hybrid article's two phases in play order: ["Assault", "Escort"].
    A Hybrid map's first section is a capture point, the rest a payload."""
    match = PHASES_RE.search(text)
    if not match:
        raise WikiError("Hybrid: the lead does not name the two modes combined")
    return [markup.tidy(link) for link in match.groups()]


def stages_of(code: str, text: str, phases: Sequence[str]) -> list[str]:
    """A map's stages by its mode; `phases` is parse_phases' result."""
    if code in ("control", "flashpoint"):
        return parse_stages(text)
    if code == "escort":
        return parse_stretches(text)
    if code == "hybrid":
        return list(phases)
    return []


# --- store ---------------------------------------------------------------------

MAPS_PAGE = "Maps"


class MapsSummary(ArticlePullSummary):
    modes: int
    maps: int
    combinations: int
    stages: int
    maps_with_stages: dict[str, int]


def run(connection: psycopg.Connection, pull: fetch.PullContext) -> MapsSummary:
    """Upsert the modes, the maps and their combinations from the Maps
    article, and each map's stages from its own article -> the modes, maps,
    combinations and stages stored, and the articles that would not fetch."""
    modes = parse_modes_and_maps(fetch_wikitext(pull, MAPS_PAGE))

    cursor = connection.cursor()
    source_id = psql.register_source(cursor, WIKI, psql.now())
    map_ids: dict[str, int] = {}
    combinations = 0
    for code, name, maps in modes:
        cursor.execute(
            # Upserted, never deleted: map_meta snapshots hang off maps, and
            # a DELETE here cascades through every older snapshot's rows.
            "INSERT INTO game_modes (code, name, source_id) VALUES (%s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
            " source_id = EXCLUDED.source_id, cao = now() RETURNING mode_id",
            (code, name, source_id),
        )
        mode_id = psql.scalar(cursor)
        for map_name in maps:
            if map_name not in map_ids:
                cursor.execute(
                    "INSERT INTO maps (name, source_id) VALUES (%s, %s)"
                    " ON CONFLICT (name) DO UPDATE SET"
                    " source_id = EXCLUDED.source_id, cao = now()"
                    " RETURNING map_id",
                    (map_name, source_id),
                )
                map_ids[map_name] = psql.scalar(cursor)
            cursor.execute(
                "INSERT INTO map_modes (map_id, mode_id, source_id)"
                " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (map_ids[map_name], mode_id, source_id),
            )
            combinations += 1
        pull.log("  %-11s %2d maps" % (name, len(maps)))

    phases = parse_phases(fetch_wikitext(pull, HYBRID_PAGE))
    # a map in two modes takes its stages from the first
    codes = {map_name: code for code, _, maps in reversed(modes) for map_name in maps}
    # a map whose article will not fetch keeps the stages it had: map_stages
    # is upserted, never deleted
    articles = fetch_articles(pull, map_ids)
    stage_rows = 0
    staged: dict[str, int] = {}
    for map_name, text in articles.found.items():
        map_id = map_ids[map_name]
        stages = stages_of(codes[map_name], text, phases)
        if stages:
            staged[codes[map_name]] = staged.get(codes[map_name], 0) + 1
            pull.log("  %-22s %s" % (map_name, " > ".join(stages)))
        for position, stage in enumerate(stages, start=1):
            cursor.execute(
                "INSERT INTO map_stages (map_id, position, name, source_id)"
                " VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (map_id, name) DO UPDATE SET"
                " position = EXCLUDED.position,"
                " source_id = EXCLUDED.source_id, cao = now()",
                (map_id, position, stage, source_id),
            )
            stage_rows += 1
    connection.commit()
    return {"modes": len(modes), "maps": len(map_ids),
            "combinations": combinations, "stages": stage_rows,
            "maps_with_stages": staged, "missing": articles.missing,
            "tables": ["game_modes", "maps", "map_modes", "map_stages"]}
