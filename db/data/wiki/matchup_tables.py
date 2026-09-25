"""Reading a hero article's "Match-Ups and Team Synergy" section.

The section holds one table per role, a row per other hero, and in each
row a Match-Up cell (advice about that hero as an enemy) and a Team
Synergy cell (advice about it as a teammate). The wiki writes the tables
two ways - a wikitable, or a {{MatchupTable/<Role>}} template with
<Hero>_matchup and <Hero>_synergy parameters and their ratings.
section_rows reads one column of either into rows, and paragraphs reads a
cell as plain text. The synergies pull reads the Team Synergy column, the
counters pull (matchups) the Match-Up one, both of every released hero's
article as released_articles fetches them. No run(): nothing here stores.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import NamedTuple

import psycopg

from db.data.fetch import PullContext
from db.data.wiki import Articles, fetch_articles, markup

SECTION_RE = re.compile(r"^==(?!=)[^=\n]*synergy[^=\n]*==[ \t]*$", re.M | re.I)
ROW_SPLIT_RE = re.compile(r"^\|-.*$", re.M)
CELL_ATTRIBUTES_RE = re.compile(r"^[^\[\]{}<>|]*\|(?!\|)")
PARAGRAPH_RE = re.compile(r"<br\s*/?>|\n\s*\n", re.I)
TABLE_END_RE = re.compile(r"\s\|\}\s*$", re.M)
LINK_PARAM_RE = re.compile(r"\|\s*link\s*=\s*([^|\]]+)")
FILE_TARGET_RE = re.compile(r"\s*(?:file|image)\s*:", re.I)
# A sentence ends at . ! or ? before a capital; the period of an initial
# ("D.Va", "B.O.B.") does not end one.
SENTENCE_END_RE = re.compile(r"(?<![ .][A-Z])[.!?](?=\s+[A-Z\"'])")

# A cell whose text keys to one of these holds no advice: "(To be added)".
PLACEHOLDERS = {"", "tobeadded", "tba", "tbd", "na", "none", "todo"}


class Released(NamedTuple):
    """The released heroes, {name: hero_id} in name order, and what
    fetch_articles read of their articles."""
    heroes: dict[str, int]
    articles: Articles


def released_articles(cursor: psycopg.Cursor, pull: PullContext) -> Released:
    """Every released hero and its article: what the synergies and counters
    pulls read before either writes."""
    cursor.execute("SELECT name, hero_id FROM heroes WHERE status = 'released' ORDER BY name")
    heroes: dict[str, int] = dict(cursor.fetchall())
    return Released(heroes, fetch_articles(pull, heroes))


def synergy_section(text: str) -> str:
    """The article's synergy section, its subsections included, or '' when
    it has none."""
    match = SECTION_RE.search(text)
    return markup.section_body(text, match.end(), top_level=True) if match else ""


def _cells(row: str) -> list[str]:
    """The cells of one wikitable row; a cell runs until the next | or ! line."""
    cells = []
    for line in row.split("\n"):
        if line[:1] in ("|", "!") and line[:2] not in ("|}", "|-", "|+"):
            cells.append(line[1:])
        elif cells:
            cells[-1] += "\n" + line
    cells = [TABLE_END_RE.split(cell)[0] for cell in cells]
    return [CELL_ATTRIBUTES_RE.sub("", cell, count=1).strip() for cell in cells]


def _row_hero(cell: str) -> str | None:
    """The hero a row is about: its article link, else its icon's link=."""
    for link in markup.LINK_RE.finditer(cell):
        if not FILE_TARGET_RE.match(link.group(1)):
            return link.group(1).strip()
    match = LINK_PARAM_RE.search(cell)
    return match.group(1).strip() if match else None


@dataclass(frozen=True)
class Column:
    """A column of the section's tables: the word its wikitable heading holds
    and its position when a table has no heading row; its template parameter
    and that parameter's rating parameters."""
    heading: str
    position: int
    parameter: str
    ratings: tuple[str, ...]


SYNERGY = Column(heading="synergy", position=2, parameter="synergy",
                 ratings=("synergy_rating",))
MATCHUP = Column(heading="match", position=1, parameter="matchup", ratings=("rating", "risk"))


class Row(NamedTuple):
    """One row of the section's tables: the hero it is about and the text of
    one cell - the markup as section_rows reads it, or the plain advice
    synergies.parse_synergies makes of it."""
    hero: str
    cell: str


def _table_rows(table: str, heading: str, position: int) -> Iterator[Row]:
    """Row(hero, cell of one column) per data row of one wikitable."""
    for row in ROW_SPLIT_RE.split(table):
        cells = _cells(row)
        if not cells:
            continue
        headers = [i for i, cell in enumerate(cells) if heading in cell.lower()
                   and len(cell) < 60]
        if headers and _row_hero(cells[0]) is None:
            position = headers[0]
            continue
        hero = _row_hero(cells[0])
        if hero and len(cells) > position:
            yield Row(hero=hero, cell=cells[position])


def _template_rows(section: str, parameter: str,
                   ratings: Sequence[str]) -> Iterator[Row]:
    """Row(hero key, rated cell of one column) per hero of each {{MatchupTable/...}}."""
    suffix = "_" + parameter
    for block in markup.find_templates(section, r"MatchupTable"):
        params = markup.parse_params(block)
        for key, value in params.items():
            if key.endswith(suffix):
                hero = key[: -len(suffix)]
                rated = [params.get("%s_%s" % (hero, rating), "").strip() for rating in ratings]
                rating = " | ".join(r for r in rated if r)
                yield Row(hero=hero, cell="'''%s''' %s" % (rating, value) if rating else value)


def section_rows(text: str, column: Column = SYNERGY) -> list[Row]:
    """[Row(hero, cell)] - one column of the section's tables, in either markup.
    A template's ratings lead its cell in bold, as a wikitable writes them."""
    section = synergy_section(text)
    rows = list(_template_rows(section, column.parameter, column.ratings))
    for table in markup.TABLE_RE.findall(section):
        rows.extend(_table_rows(table, column.heading, column.position))
    return rows


def paragraphs(cell: str) -> list[str]:
    """A cell's paragraphs as plain text, the empty ones dropped."""
    text = markup.REF_RE.sub("", markup.COMMENT_RE.sub("", cell))
    text = markup.FILE_LINK_RE.sub("", text)
    texts = (markup.wikitext_to_text(p.replace("\n", " ")) for p in PARAGRAPH_RE.split(text))
    return [text for text in texts if text]
