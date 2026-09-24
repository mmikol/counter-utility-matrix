"""Pull + clean + store: overwatch.fandom.com - hero synergies.

Every hero article has a "Match-Ups and Team Synergy" section: one table
per role, a row per other hero, a Team Synergy cell of advice. The wiki
writes the tables two ways - a wikitable, or a {{MatchupTable/<Role>}}
template with <Hero>_synergy and <Hero>_synergy_rating parameters.

A cell is a claim when it holds advice for the pair: not a placeholder
("To be added"), not rated below GOOD (SITUATIONAL, OK, WEAK, POOR, BAD) or
MIRROR, and, unrated, not opening with "no notable synergy" or the like. A
pair is stored once, lower hero_id first. score 2 when both articles claim the pair, 1
when one does. note is the first sentence of the advice, cut to a clause
under 120 characters. The table is reloaded wholesale.
"""

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import TypedDict

import psycopg
import requests

from db import psql
from db.data import fetch
from db.data.names import index, name_key
from db.data.wiki import WIKI, WikiError, fetch_wikitext, markup

# --- extract: markup -> Python ---------------------------------------------

NOTE_LIMIT = 120

SECTION_RE = re.compile(r"^==(?!=)[^=\n]*synergy[^=\n]*==[ \t]*$", re.M | re.I)
TOP_HEADING_RE = re.compile(r"^==(?!=).*==[ \t]*$", re.M)
TABLE_RE = re.compile(r"^\{\|.*?^\|\}", re.M | re.S)
ROW_SPLIT_RE = re.compile(r"^\|-.*$", re.M)
CELL_ATTRIBUTES_RE = re.compile(r"^[^\[\]{}<>|]*\|(?!\|)")
REF_RE = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
PARAGRAPH_RE = re.compile(r"<br\s*/?>|\n\s*\n", re.I)
# "STRONG SYNERGY advice", or "(6v6 Exclusive Pairing - Weak Synergy) advice".
RATING_RE = re.compile(r"^(?:\s|<[^>]+>|'{2,5})*(?:([A-Z ]*?)\s*SYNERGY\b"
                       r"|\((?:[^()]*? - )?(?i:([a-z ]*?)\s*synergy)\))(?:\s|'{2,5})*")
TABLE_END_RE = re.compile(r"\s\|\}\s*$", re.M)
LINK_PARAM_RE = re.compile(r"\|\s*link\s*=\s*([^|\]]+)")
# An innermost link: a file's caption may hold the hero's link.
ROW_LINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|[^\[\]]*)?\]\]")
FILE_TARGET_RE = re.compile(r"\s*(?:file|image)\s*:", re.I)
# A sentence ends at . ! or ? before a capital; the period of an initial
# ("D.Va", "B.O.B.") does not end one.
SENTENCE_END_RE = re.compile(r"(?<![ .][A-Z])[.!?](?=\s+[A-Z\"'])")
CLAUSE_END_RE = re.compile(r"[,;:]\s| - | \(")
# "With a friendly Sigma on your team, ..." - an opener, not the advice.
OPENER_RE = re.compile(r"(?:if|when|while|with|because|since|as|though|although|should|like"
                       r"|just like|unlike|in|for|due to|thanks to)\b[^,]*,\s+", re.I)

PLACEHOLDERS = {"", "tobeadded", "tba", "tbd", "na", "none", "todo"}
# A rated cell is a claim unless rated one of these; "tba" is no rating.
NOT_A_SYNERGY = {"situational", "ok", "weak", "very weak", "poor", "very poor",
                 "bad", "no", "mirror"}
UNRATED = {"", "tba", "tbd"}
# An unrated cell is a claim unless its first sentence says there is none.
NO_SYNERGY_RE = re.compile(
    r"\b(?:no|not|n't|poor|little|few)\b[^.]{0,40}\bsynerg"
    r"|\bstruggles?\b|\bsynergi[sz]ing\b[^.]*\bdifficult"
    r"|\bnot (?:the best|a good) (?:pair|match)|\bdon't really mix"
    r"|\bdo not share\b|\brarely interact|\b(?:low|weak\w*) (?:synerg|pairing)", re.I)
# A hero the wiki's older rows still link under a former name.
RENAMED = {"mccree": "cassidy"}


def synergy_section(text: str) -> str:
    """The article's synergy section, or '' when it has none."""
    match = SECTION_RE.search(text)
    if not match:
        return ""
    body = text[match.end():]
    following = TOP_HEADING_RE.search(body)
    return body[: following.start()] if following else body


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
    for target in ROW_LINK_RE.findall(cell):
        if not FILE_TARGET_RE.match(target):
            return target.strip()
    match = LINK_PARAM_RE.search(cell)
    return match.group(1).strip() if match else None


# A column of the section's tables: the word its wikitable heading holds and
# its position when a table has no heading row; its template parameter and
# that parameter's rating parameters.
Column = tuple[str, int, str, tuple[str, ...]]
SYNERGY: Column = ("synergy", 2, "synergy", ("synergy_rating",))
MATCHUP: Column = ("match", 1, "matchup", ("rating", "risk"))


def _table_rows(table: str, heading: str, position: int) -> Iterator[tuple[str, str]]:
    """(hero, cell of one column) per data row of one wikitable."""
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
            yield hero, cells[position]


def _template_rows(section: str, parameter: str,
                   ratings: Sequence[str]) -> Iterator[tuple[str, str]]:
    """(hero key, rated cell of one column) per hero of each {{MatchupTable/...}}."""
    suffix = "_" + parameter
    for block in markup.find_templates(section, r"MatchupTable"):
        params = markup.parse_params(block)
        for key, value in params.items():
            if key.endswith(suffix):
                hero = key[: -len(suffix)]
                rated = [params.get("%s_%s" % (hero, rating), "").strip() for rating in ratings]
                rating = " | ".join(r for r in rated if r)
                yield hero, "'''%s''' %s" % (rating, value) if rating else value


def section_rows(text: str, column: Column = SYNERGY) -> list[tuple[str, str]]:
    """[(hero, cell)] - one column of the section's tables, in either markup.
    A template's ratings lead its cell in bold, as a wikitable writes them."""
    heading, position, parameter, ratings = column
    section = synergy_section(text)
    rows = list(_template_rows(section, parameter, ratings))
    for table in TABLE_RE.findall(section):
        rows.extend(_table_rows(table, heading, position))
    return rows


def split_rating(cell: str) -> tuple[str | None, str]:
    """'''STRONG SYNERGY''' advice -> ('strong', advice). No rating -> (None, cell)."""
    match = RATING_RE.match(cell)
    if not match:
        return None, cell
    rating = (match.group(1) or match.group(2) or "").strip().lower()
    return (None if rating in UNRATED else rating), cell[match.end():]


def paragraphs(cell: str) -> list[str]:
    """A cell's paragraphs as plain text, the empty ones dropped."""
    text = REF_RE.sub("", markup.COMMENT_RE.sub("", cell))
    text = markup.FILE_LINK_RE.sub("", text)
    texts = (markup.wikitext_to_text(p.replace("\n", " ")) for p in PARAGRAPH_RE.split(text))
    return [text for text in texts if text]


def plain(cell: str) -> str:
    """The first paragraph of a cell's advice as plain text."""
    return next(iter(paragraphs(cell)), "")


def clause(text: str, limit: int = NOTE_LIMIT) -> str:
    """The first sentence, cut to a clause under `limit` characters: a long
    sentence loses its opener, then everything past its last clause that fits."""
    end = SENTENCE_END_RE.search(text)
    sentence = text[: end.start()] if end else text
    sentence = sentence.strip().rstrip(".!?;:, ")
    if len(sentence) < limit:
        return sentence
    opener = OPENER_RE.match(sentence)
    if opener:
        sentence = sentence[opener.end()].upper() + sentence[opener.end() + 1:]
        if len(sentence) < limit:
            return sentence
    cuts = [m.start() for m in CLAUSE_END_RE.finditer(sentence) if 30 <= m.start() < limit]
    if cuts:
        return sentence[: cuts[-1]].rstrip(".;:, ")
    return sentence[:limit].rsplit(" ", 1)[0].rstrip(".;:, ")


def parse_synergies(text: str) -> list[tuple[str, str]]:
    """[(teammate name, advice)] - the claims one article's synergy cells make."""
    claims = []
    for hero, cell in section_rows(text):
        rating, advice = split_rating(cell)
        advice = plain(advice)
        if name_key(advice) in PLACEHOLDERS or rating in NOT_A_SYNERGY:
            continue
        if rating is None and NO_SYNERGY_RE.search(clause(advice, 10 ** 6)):
            continue
        claims.append((hero, advice))
    return claims


# {(low id, high id): (score, note)}
Pairs = dict[tuple[int, int], tuple[int, str]]


def pair_up(claims_by_hero: Mapping[str, list[tuple[str, str]]],
            hero_ids: Mapping[str, int]) -> tuple[Pairs, list[str]]:
    """Claims per hero -> ({(low id, high id): (score, note)}, unresolved names).

    claims_by_hero is {hero name: [(teammate name, advice)]}; hero_ids is
    {name_key: hero_id}. The note comes from an article whose first sentence
    fits uncut when there is one, else from the first article by hero name.
    """
    stated: dict[tuple[int, int], dict[int, str]] = {}
    unmatched: list[str] = []
    for hero in sorted(claims_by_hero):
        hero_id = hero_ids[name_key(hero)]
        for teammate, advice in claims_by_hero[hero]:
            key = name_key(teammate)
            other_id = hero_ids.get(RENAMED.get(key, key))
            if other_id is None:
                unmatched.append("%s: %s" % (hero, teammate))
            elif other_id != hero_id:
                pair = (min(hero_id, other_id), max(hero_id, other_id))
                stated.setdefault(pair, {}).setdefault(hero_id, advice)

    pairs = {}
    for pair, advice_by_hero in stated.items():
        notes = list(advice_by_hero.values())
        uncut = [n for n in notes if clause(n) == clause(n, 10 ** 6)]
        pairs[pair] = (len(advice_by_hero), clause((uncut or notes)[0]))
    return pairs, unmatched


# --- store ---------------------------------------------------------------------

class SynergiesSummary(TypedDict):
    synergies: int
    mutual: int
    articles: int
    unpaired: list[str]
    unmatched: list[str]
    tables: list[str]


def run(connection: psycopg.Connection, cache_dir: str | None = None,
        session: requests.Session | None = None,
        log: Callable[[str], None] = print) -> SynergiesSummary:
    session = fetch.session(session)
    cursor = connection.cursor()
    cursor.execute("SELECT name, hero_id FROM heroes WHERE status = 'released' ORDER BY name")
    released: dict[str, int] = dict(cursor.fetchall())

    claims: dict[str, list[tuple[str, str]]] = {}
    missing: list[str] = []
    for name in released:
        try:
            claims[name] = parse_synergies(fetch_wikitext(session, name, cache_dir))
        except fetch.FetchError as error:
            missing.append("%s: %s" % (name, error))
    if not any(claims.values()):
        raise WikiError("no hero article has a synergy claim")
    pairs, unmatched = pair_up(claims, index(released))

    source_id = psql.register_source(cursor, WIKI, psql.now())
    cursor.execute("DELETE FROM synergies")
    for (hero_id, other_id), (score, note) in sorted(pairs.items()):
        cursor.execute(
            "INSERT INTO synergies (hero_id, other_id, score, note, source_id)"
            " VALUES (%s, %s, %s, %s, %s)",
            (hero_id, other_id, score, note, source_id))
    connection.commit()

    paired = {hero_id for pair in pairs for hero_id in pair}
    unpaired = []
    for name, hero_id in released.items():
        if hero_id not in paired:
            reason = ("no article" if name not in claims else
                      "its claims name no released hero" if claims[name] else
                      "no advice in its article or about it in another")
            unpaired.append("%s: %s" % (name, reason))
    mutual = sum(1 for score, _ in pairs.values() if score == 2)
    log("  synergies  %d pairs (%d mutual) from %d articles; %d heroes unpaired"
        % (len(pairs), mutual, sum(1 for c in claims.values() if c), len(unpaired)))
    return {"synergies": len(pairs), "mutual": mutual,
            "articles": sum(1 for c in claims.values() if c),
            "unpaired": unpaired, "unmatched": unmatched + missing,
            "tables": ["synergies"]}
