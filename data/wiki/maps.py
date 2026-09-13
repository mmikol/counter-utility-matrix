"""Pull + clean + store: overwatch.fandom.com - maps, game modes, stages.

Only the wiki's "Standard Play" section is read; Former Standard Play,
Stadium, Arcade, Custom Games, Training and seasonal modes are out of scope.

Extracting maps and game modes from the wiki's Maps article.

Only the "Standard Play" section is read; Former Standard Play (Assault,
Clash), Stadium, Arcade and seasonal modes are out of scope.

    python -m data.wiki.maps
"""

import sys
import psycopg
import requests
from data import common
from data.wiki import WIKI, USER_AGENT, WikiError, fetch_wikitext
import re


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
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")

MODE_NAMES = {
    "control": "Control",
    "escort": "Escort",
    "flashpoint": "Flashpoint",
    "hybrid": "Hybrid",
    "push": "Push",
}


def standard_play_section(text):
    """Just the Standard Play part of the article."""
    try:
        start = text.index(SECTION_START)
    except ValueError:
        raise WikiError("Maps: no %r heading" % SECTION_START)
    end = text.find(SECTION_END, start)
    return text[start:end if end != -1 else len(text)]


def parse_modes_and_maps(text):
    """[(mode_code, mode_name, [map_name])] in page order."""
    section = standard_play_section(text)
    modes = []
    for match in GALLERY_RE.finditer(section):
        code = match.group(1).lower()
        if code not in MODE_NAMES:
            continue

        maps = []
        for line in MAP_LINE_RE.findall(match.group(2)):
            link = LINK_RE.search(line)
            if link:
                maps.append(link.group(1).strip())

        modes.append((code, MODE_NAMES[code], maps))

    if not modes:
        raise WikiError("Maps: no mode galleries found in Standard Play")
    return modes


# --- stages (submaps) --------------------------------------------------

GAMEPLAY_SECTION_RE = re.compile(
    r'^==\s*Gameplay\s*==\s*$(.*?)(?=^==|\Z)', re.M | re.S)
LINK_TEXT_RE = re.compile(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]')


def parse_stages(text):
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
    cut = re.search(r'^===', body, re.M)
    if cut:
        body = body[:cut.start()]
    stages = []
    for line in body.splitlines():
        if not line.startswith('*') or line.startswith('**'):
            continue
        name = LINK_TEXT_RE.sub(r'\1', line.lstrip('* ').strip())
        name = re.sub(r'\s*\([A-Z]\)\s*$', '', name).strip("'\" ")
        if name and len(name) <= 40 and '. ' not in name:
            stages.append(name)
    return stages if len(stages) >= 2 else []


# --- store ---------------------------------------------------------------------

MAPS_PAGE = "Maps"


def run(connection, cache_dir=None, session=None, log=print):
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    modes = parse_modes_and_maps(fetch_wikitext(session, MAPS_PAGE, cache_dir))

    cursor = connection.cursor()
    source_id = common.register_source(cursor, WIKI, common.now())
    map_ids, combinations = {}, 0
    for code, name, maps in modes:
        cursor.execute(
            # Upserted, never deleted: map_meta snapshots hang off maps, and
            # a DELETE here cascades through every older snapshot's rows.
            "INSERT INTO game_modes (code, name, source_id) VALUES (%s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
            " source_id = EXCLUDED.source_id, cao = now() RETURNING mode_id",
            (code, name, source_id),
        )
        mode_id = cursor.fetchone()[0]
        for map_name in maps:
            if map_name not in map_ids:
                cursor.execute(
                    "INSERT INTO maps (name, source_id) VALUES (%s, %s)"
                    " ON CONFLICT (name) DO UPDATE SET"
                    " source_id = EXCLUDED.source_id, cao = now()"
                    " RETURNING map_id",
                    (map_name, source_id),
                )
                map_ids[map_name] = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO map_modes (map_id, mode_id, source_id)"
                " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (map_ids[map_name], mode_id, source_id),
            )
            combinations += 1
        log("  %-11s %2d maps" % (name, len(maps)))

    stage_rows = 0
    for map_name, map_id in map_ids.items():
        for position, stage in enumerate(
            parse_stages(fetch_wikitext(session, map_name.replace(" ", "_"),
                                        cache_dir)), start=1):
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
            "tables": ["game_modes", "maps", "map_modes", "map_stages"]}


def main():
    parser = common.build_parser(__doc__, ".cache-wiki")
    args = parser.parse_args()
    cache = common.prepare_cache(args.cache)
    with psycopg.connect(common.resolve_dsn(args)) as connection:
        summary = run(connection, cache)
        common.export_raw(connection, args, summary["tables"])
    print("modes: %(modes)d   maps: %(maps)d   combinations: %(combinations)d"
          "   stages: %(stages)d" % summary)


if __name__ == "__main__":
    try:
        main()
    except (WikiError, psycopg.Error, requests.RequestException) as error:
        sys.exit("error: %s" % error)
