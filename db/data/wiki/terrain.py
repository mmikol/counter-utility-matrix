"""Pull + clean + store: overwatch.fandom.com - each map's terrain.

A map's article describes its ground and how it is played. The sections that
do are kept, the lore is dropped, and the mentions of each terrain feature
are counted: per map and feature, the count and the count per thousand words
of the kept text. The same is counted per stage over the text the article
has about that stage. Both tables are reloaded wholesale.
"""

import re
from collections.abc import Mapping
from typing import NamedTuple

import psycopg
from psycopg.sql import SQL

from db import psql
from db.data import ArticlePullSummary, fetch
from db.data.wiki import WIKI, fetch_articles, markup
from db.data.wiki.maps import parse_stretches

# --- extract: article -> the text about the ground -------------------------

HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)

# Headings whose section, subsections included, is not about the ground:
# lore, people, place-name lists, media, other modes and event versions.
# "Description" (Blizzard's patch-note blurb, which names the ground) stays;
# "Official Description" (the launch lore) goes.
DROPPED_HEADING_RE = re.compile(
    r"background|history|lore|trivia|development|official description"
    r"|media|screenshots?|images?|gallery|videos?|audio|music|panorama"
    r"|references?|locations|known\b|unique features"
    r"|stadium|l[uú]cioball|halloween|winter wonderland|lunar new year",
    re.I)
# A rework's own subsection states the ground as it now is; it is kept
# wherever it sits ("Development" > "Season 13 rework").
REWORK_HEADING_RE = re.compile(r"\brework\b(?! images)|design changes", re.I)

# Dropped whole before the markup is stripped, beside markup's citations,
# tables (quote and voice-line lists) and files with their captions:
# galleries, and templates (ability and hero names, infoboxes, stub notices).
GALLERY_RE = re.compile(r"<gallery[^>]*>.*?</gallery>", re.S | re.I)
INNER_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
# The placeholder an empty section carries.
BLANK_NOTICE_RE = re.compile(r"This section is currently blank\.[^\n]*", re.I)
# The infobox's own word on the ground: "| terrain = Narrow cobblestone streets".
INFOBOX_TERRAIN_RE = re.compile(r"^\|\s*terrain\s*=\s*(.+?)\s*$", re.M | re.I)
WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")

# A list item under this many words is a name - a stage, a hero whose
# abilities were templates - not prose.
LIST_PROSE_WORDS = 4
# Under this many words of kept text an article says nothing usable.
MIN_WORDS = 60
# A rate of mentions is per this many words of kept text.
WORDS_PER_RATE = 1000
# The same for one stage. A stage's text is short: Samoa's Volcano is one
# sentence of 20 words, and it names the lava moat round the point.
STAGE_MIN_WORDS = 20


class Section(NamedTuple):
    """An article's section: its heading path, outermost first, and its body."""
    path: tuple[str, ...]
    body: str


def sections(text: str) -> list[Section]:
    """[Section(heading path, body)] in article order; the lead's path is ()."""
    out: list[Section] = []
    path: list[tuple[int, str]] = []
    position = 0
    matches = list(HEADING_RE.finditer(text))
    for index, match in enumerate([None, *matches]):
        end = matches[index].start() if index < len(matches) else len(text)
        if match is not None:
            depth = len(match.group(1))
            path = [(d, title) for d, title in path if d < depth]
            path.append((depth, markup.TAG_RE.sub("", match.group(2)).strip()))
            position = match.end()
        out.append(Section(tuple(title for _, title in path), text[position:end]))
    return out


def is_kept(path: tuple[str, ...]) -> bool:
    """A section is kept unless its heading, or one above it, is dropped; a
    rework's own section is kept regardless. The lead is dropped: it states
    the mode and the release date."""
    if not path:
        return False
    if REWORK_HEADING_RE.search(path[-1]):
        return True
    return not any(DROPPED_HEADING_RE.search(title) for title in path)


def stripped(body: str) -> str:
    """A section's wikitext without what is dropped whole."""
    for pattern in (markup.COMMENT_RE, markup.REF_RE, GALLERY_RE, markup.TABLE_RE,
                    markup.FILE_LINK_RE):
        body = pattern.sub(" ", body)
    previous: str | None = None
    while previous != body:
        previous, body = body, INNER_TEMPLATE_RE.sub(" ", body)
    return BLANK_NOTICE_RE.sub(" ", body)


def section_prose(body: str) -> str:
    """Stripped wikitext -> its prose, the list items that are names dropped."""
    lines = []
    for line in body.splitlines():
        if line.startswith(("*", "#")):
            line = line.lstrip("*#:; ")
            if word_count(markup.wikitext_to_text(line)) < LIST_PROSE_WORDS:
                continue
        lines.append(line)
    return markup.wikitext_to_text("\n".join(lines))


def section_plain(body: str) -> str:
    """A section's wikitext -> its prose."""
    return section_prose(stripped(body))


def section_paragraphs(body: str) -> list[str]:
    """A section's wikitext -> the prose of each paragraph and list item."""
    blocks: list[str] = []
    open_block = False
    for line in stripped(body).splitlines():
        if not line.strip():
            open_block = False
        elif line.startswith(("*", "#")) or not open_block:
            blocks.append(line)
            open_block = not line.startswith(("*", "#"))
        else:
            blocks[-1] += "\n" + line
    return [text for text in map(section_prose, blocks) if text]


def terrain_text(text: str) -> str:
    """The article's text about the ground: the infobox's terrain line, then
    every kept section's heading and prose."""
    parts = [markup.wikitext_to_text(m) for m in INFOBOX_TERRAIN_RE.findall(text)]
    for path, body in sections(text):
        if is_kept(path):
            parts += [markup.tidy(path[-1]), section_plain(body)]
    return " . ".join(part for part in parts if part)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def stage_texts(text: str, stages: list[str], phases: bool = False) -> dict[str, str]:
    """{stage: the article's text about it}, every stage present.

    A stage's text is every kept section under a heading that names it, and
    every paragraph or list item elsewhere that names it and no other stage
    ("On the Well section of the map, the big hole ..."). `phases`: the
    stages are a Hybrid map's two phases. A phase's text is every Assault or
    Escort section, attack and defense alike; where the article names the
    route's stretches, the first is the capture point's and the rest the
    payload's. A phase's name is a mode's, so no paragraph is read for it.
    """
    headings = {stage: {stage.casefold()} for stage in stages}
    if phases:
        stretches = [name.casefold() for name in parse_stretches(text)]
        headings[stages[0]].update(stretches[:1])
        headings[stages[-1]].update(stretches[1:])
    named = {stage: re.compile(r"\b%s\b" % re.escape(stage)) for stage in stages}
    parts: dict[str, list[str]] = {stage: [] for stage in stages}
    for path, body in sections(text):
        if not is_kept(path):
            continue
        titles = {title.casefold() for title in path}
        under = [stage for stage in stages if titles & headings[stage]]
        if under:
            parts[under[0]] += [markup.tidy(path[-1]), section_plain(body)]
        elif not phases:
            for paragraph in section_paragraphs(body):
                about = [s for s in stages if named[s].search(paragraph)]
                if len(about) == 1:
                    parts[about[0]].append(paragraph)
    return {stage: " . ".join(part for part in found if part)
            for stage, found in parts.items()}


# --- the lexicon: one pattern per terrain feature --------------------------

def _pattern(*alternatives: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:%s)\b" % "|".join(alternatives), re.I)


# Chokes: where a team must pass through a narrow place.
CHOKES_RE = _pattern(
    r"choke(?:\s?-?\s?points?|s)?", r"bottle\s?-?necks?",
    r"(?:narrow|tight|cramped)(?:er|est)?\s+(?:\w+\s+)?(?:streets?|roads?"
    r"|passage(?:way)?s?|alley(?:way)?s?|path(?:way)?s?|halls?|hallways?"
    r"|corridors?|tunnels?|entrances?|entryways?|gaps?|doorways?|bridges?"
    r"|spaces?|quarters|areas?|turns?)",
    r"corridors?", r"hallways?", r"tunnels?", r"alley(?:way)?s?",
    r"gate(?:way)?s?", r"doorways?", r"archways?")

# Interiors: fights held indoors.
INTERIORS_RE = _pattern(
    r"indoors?", r"interiors?", r"enclosed", r"closer?[- ]quarters?",
    r"(?:inside|into|through|within)\s+(?:of\s+)?(?:the|a|an)\s+(?:\w+\s+){0,2}"
    r"(?:buildings?|rooms?|castle|hotel|house|temple|facility|station|bunker"
    r"|warehouse|volcano|cave)",
    r"(?<!spawn )(?<!spawn-)rooms?", r"caves?", r"caverns?", r"underground")

# High ground: positions above the fight.
HIGH_GROUND_RE = _pattern(
    r"high(?:er)?[- ]?grounds?", r"roof(?:top)?s?", r"balcon(?:y|ies)",
    r"ledges?", r"catwalks?", r"walkways?", r"vertical(?:ity)?",
    r"elevat(?:ed|ions?)", r"overlook(?:s|ing)?", r"vantage(?:\s+points?)?",
    r"(?:upper|top)\s+(?:floor|level|area|deck)s?",
    r"second\s+(?:floor|level|storey|story)s?", r"two-stor(?:e)?y",
    r"upstairs", r"stair(?:s|cases?|ways?)", r"from above", r"overpass(?:es)?",
    r"inclines?", r"uphill")

# Flanks: ways around the main line.
FLANKS_RE = _pattern(
    r"flank(?:s|ed|ing|ers?)?",
    r"side\s+(?:path|route|passage|room|street|alley|door|entrance|road)s?",
    r"alternat(?:e|ive)\s+(?:route|path|way|entrance)s?",
    r"back\s?(?:route|way|door|entrance|alley)s?", r"shortcuts?",
    r"sneak(?:s|ing)?\s+(?:around|behind|past)",
    r"(?:multiple|several|many)\s+(?:routes|paths|entrances|ways)")

# Sightlines: long views a ranged hero holds.
SIGHTLINES_RE = _pattern(
    r"sight\s?-?lines?", r"lines?\s+of\s+sight", r"long[- ]?range(?:d)?",
    r"long[- ]?distances?",
    r"long(?:er|est)?\s+(?:\w+\s+)?(?:streets?|roads?|stretch(?:es)?|straights?"
    r"|halls?|hallways?|corridors?|views?|lanes?|paths?|bridges?)",
    r"snip(?:e|es|ers?|ing)", r"from\s+afar", r"from\s+a\s+distance")

# Open ground: wide spaces with little to stand behind; cover said to be
# missing is counted here, not under cover.
OPEN_GROUND_RE = _pattern(
    r"open\s+(?:area|space|ground|field|plaza|square|courtyard|street|terrain"
    r"|air|layout|room|sk(?:y|ies)|stretch|stretche)s?",
    r"(?:no|little|minimal|less|isn't\s+much|not\s+much|lack\s+of|without"
    r"|fewer\s+places\s+to\s+take)\s+cover",
    r"wide[- ]open", r"(?:out\s+)?in\s+the\s+open", r"open(?:ness)?\s+of\s+the",
    r"(?:more|very|quite|fairly|rather|mostly|relatively)\s+open",
    r"plazas?", r"courtyards?", r"exposed",
    r"(?:wide|spacious|large|big|broad|vast)\s+(?:\w+\s+)?(?:areas?|spaces?"
    r"|streets?|roads?|rooms?|fields?)")

# Hazards: ground that kills - drops, pits, wells, cliffs.
HAZARDS_RE = _pattern(
    r"environmental\s+(?:kill|hazard|elimination|death)s?", r"pit(?:s|falls?)?",
    r"cliff(?:s|sides?)?", r"(?:big|large|giant|huge|deep)\s+holes?",
    r"(?:the|a)\s+well(?![- ]known)", r"abyss", r"chasms?", r"bottomless",
    r"lava", r"moats?", r"knockbacks?(?:\s+kills?)?",
    r"(?:deadly|long|steep|sheer|fatal|big|large)\s+drops?", r"drop-?offs?",
    r"off\s+(?:of\s+)?the\s+(?:map|edge|cliff|side|bridge|ledge|stage|point)",
    r"(?:fall|falls|falling|fell)\s+off",
    r"(?:knock|push|boop|launch|throw|blast)(?:s|ed|ing)?\s+(?:\w+\s+){0,3}off",
    r"boop(?:s|ed|ing)?")

# Cover: things to stand behind. "cover" the noun only: not the verb
# ("to cover the choke"), not cover said to be missing (open ground's).
COVER_RE = _pattern(
    r"(?<!to )(?<!can )(?<!will )(?<!could )(?<!should )"
    r"(?<!no )(?<!little )(?<!minimal )(?<!less )(?<!much )(?<!lack of )"
    r"(?<!without )(?<!fewer places to take )"
    r"cover(?!\s+(?:the|a|an|your|their|his|her|each|all|every|both|more|most"
    r"|much|many)\b)",
    r"pillars?", r"columns?", r"barricades?", r"obstacles?", r"crates?",
    r"(?:hide|hides|hiding)\s+behind",
    r"behind\s+(?:the\s+|a\s+)?(?:walls?|corners?)")

FEATURES = {
    "chokes": CHOKES_RE,
    "interiors": INTERIORS_RE,
    "high_ground": HIGH_GROUND_RE,
    "flanks": FLANKS_RE,
    "sightlines": SIGHTLINES_RE,
    "open_ground": OPEN_GROUND_RE,
    "hazards": HAZARDS_RE,
    "cover": COVER_RE,
}


def count_features(text: str) -> dict[str, int]:
    """{feature: mentions} over a plain text, every feature present."""
    return {feature: len(pattern.findall(text))
            for feature, pattern in FEATURES.items()}


def per_thousand(mentions: int, words: int) -> float:
    """Mentions per WORDS_PER_RATE words, to two places; 0.0 over no words."""
    return round(mentions * WORDS_PER_RATE / words, 2) if words else 0.0


# --- store ---------------------------------------------------------------------

class TerrainSummary(ArticlePullSummary):
    maps: int
    without_text: list[str]
    rows: int
    words: int
    stages: int
    stages_no_text: int
    stage_rows: int


def _store(
        cursor: psycopg.Cursor, table: str, key: str, key_id: int, counts: Mapping[str, int],
        words: int, source_id: int) -> int:
    insert = SQL("INSERT INTO {} ({}, feature, mentions, per_thousand, source_id)"
                 " VALUES (%s, %s, %s, %s, %s)").format(psql.identifier(table),
                                                        psql.identifier(key))
    for feature, mentions in counts.items():
        cursor.execute(
            insert, (key_id, feature, mentions, per_thousand(mentions, words), source_id))
    return len(counts)


def _counted(counts: Mapping[str, int]) -> str:
    return "  ".join("%s %d" % (f, n) for f, n in counts.items() if n)


def run(connection: psycopg.Connection, pull: fetch.PullContext) -> TerrainSummary:
    """Reload map_terrain and stage_terrain from every map's article -> the
    maps and stages counted, the rows and words, and the maps without text."""
    cursor = connection.cursor()
    maps: list[tuple[int, str]] = cursor.execute(
        "SELECT map_id, name FROM maps ORDER BY name").fetchall()
    stages: dict[int, tuple[bool, dict[str, int]]] = {}
    for map_id, stage_id, stage, hybrid in cursor.execute(
            "SELECT s.map_id, s.stage_id, s.name, EXISTS (SELECT 1 FROM map_modes mm"
            " JOIN game_modes g USING (mode_id)"
            " WHERE mm.map_id = s.map_id AND g.code = 'hybrid')"
            " FROM map_stages s ORDER BY s.map_id, s.position").fetchall():
        stages.setdefault(map_id, (hybrid, {}))[1][stage] = stage_id

    articles = fetch_articles(pull, [name for _, name in maps])
    # every article is read before the first write: no row stays locked across a fetch
    source_id = psql.register_source(cursor, WIKI, psql.now())
    cursor.execute("DELETE FROM stage_terrain")
    cursor.execute("DELETE FROM map_terrain")
    rows, words_read, stage_rows, stages_read = 0, 0, 0, 0
    without_text: list[str] = []
    for map_id, name in maps:
        if name not in articles.found:
            continue
        article = articles.found[name]
        text = terrain_text(article)
        words = word_count(text)
        if words < MIN_WORDS:
            without_text.append(name)
            pull.log("  %-22s %4d words: no usable text" % (name, words))
        else:
            counts = count_features(text)
            rows += _store(cursor, "map_terrain", "map_id", map_id, counts, words,
                           source_id)
            words_read += words
            pull.log("  %-22s %4d words  %s" % (name, words, _counted(counts)))

        hybrid, stage_ids = stages.get(map_id, (False, {}))
        for stage, text in stage_texts(article, list(stage_ids), hybrid).items():
            words = word_count(text)
            if words < STAGE_MIN_WORDS:
                continue
            counts = count_features(text)
            stage_rows += _store(cursor, "stage_terrain", "stage_id",
                                 stage_ids[stage], counts, words, source_id)
            stages_read += 1
            pull.log("    %-30s %4d words  %s" % (stage, words, _counted(counts)))
    connection.commit()
    total_stages = sum(len(stage_ids) for _, stage_ids in stages.values())
    return {"maps": len(maps) - len(without_text) - len(articles.missing),
            "without_text": without_text, "missing": articles.missing,
            "rows": rows, "words": words_read,
            "stages": stages_read, "stages_no_text": total_stages - stages_read,
            "stage_rows": stage_rows, "tables": ["map_terrain", "stage_terrain"]}
