"""Pull + clean + store: overwatch.fandom.com - hero synergies.

Every hero article's "Match-Ups and Team Synergy" section has, per other
hero, a Team Synergy cell of advice, in either markup matchup_tables.py
reads; a template rates the cell in <Hero>_synergy_rating.

A cell is a claim when it holds advice for the pair: not a placeholder
("To be added"), not rated below GOOD (SITUATIONAL, OK, WEAK, POOR, BAD) or
MIRROR, and, unrated, not opening with "no notable synergy" or the like. A
pair is stored once, lower hero_id first. score 2 when both articles claim the pair, 1
when one does. note is the first sentence of the advice, cut to a clause
under 120 characters. The table is reloaded wholesale.
"""

import re
from collections.abc import Mapping, Sequence

import psycopg

from db import psql
from db.data import ArticlePullSummary, fetch
from db.data.names import hero_key, index, name_key
from db.data.wiki import WIKI, WikiError
from db.data.wiki.matchup_tables import (
    PLACEHOLDERS,
    SENTENCE_END_RE,
    Row,
    paragraphs,
    released_articles,
    section_rows,
)

# --- extract: markup -> Python ---------------------------------------------

NOTE_LIMIT = 120

# "STRONG SYNERGY advice", or "(6v6 Exclusive Pairing - Weak Synergy) advice".
RATING_RE = re.compile(r"^(?:\s|<[^>]+>|'{2,5})*(?:([A-Z ]*?)\s*SYNERGY\b"
                       r"|\((?:[^()]*? - )?(?i:([a-z ]*?)\s*synergy)\))(?:\s|'{2,5})*")
CLAUSE_END_RE = re.compile(r"[,;:]\s| - | \(")
# "With a friendly Sigma on your team, ..." - an opener, not the advice.
OPENER_RE = re.compile(r"(?:if|when|while|with|because|since|as|though|although|should|like"
                       r"|just like|unlike|in|for|due to|thanks to)\b[^,]*,\s+", re.I)

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


def split_rating(cell: str) -> tuple[str | None, str]:
    """'''STRONG SYNERGY''' advice -> ('strong', advice). No rating -> (None, cell)."""
    match = RATING_RE.match(cell)
    if not match:
        return None, cell
    rating = (match.group(1) or match.group(2) or "").strip().lower()
    return (None if rating in UNRATED else rating), cell[match.end():]


def plain(cell: str) -> str:
    """The first paragraph of a cell's advice as plain text."""
    return next(iter(paragraphs(cell)), "")


def first_sentence(text: str) -> str:
    """The first sentence, uncut, its closing punctuation dropped."""
    end = SENTENCE_END_RE.search(text)
    sentence = text[: end.start()] if end else text
    return sentence.strip().rstrip(".!?;:, ")


def clause(text: str) -> str:
    """The first sentence, cut to a clause under NOTE_LIMIT characters: a long
    sentence loses its opener, then everything past its last clause that fits."""
    sentence = first_sentence(text)
    if len(sentence) < NOTE_LIMIT:
        return sentence
    opener = OPENER_RE.match(sentence)
    if opener:
        sentence = sentence[opener.end()].upper() + sentence[opener.end() + 1:]
        if len(sentence) < NOTE_LIMIT:
            return sentence
    cuts = [m.start() for m in CLAUSE_END_RE.finditer(sentence) if 30 <= m.start() < NOTE_LIMIT]
    if cuts:
        return sentence[: cuts[-1]].rstrip(".;:, ")
    return sentence[:NOTE_LIMIT].rsplit(" ", 1)[0].rstrip(".;:, ")


def parse_synergies(text: str) -> list[Row]:
    """[Row(teammate name, advice)] - the claims one article's synergy cells make."""
    claims = []
    for row in section_rows(text):
        rating, advice = split_rating(row.cell)
        advice = plain(advice)
        if name_key(advice) in PLACEHOLDERS or rating in NOT_A_SYNERGY:
            continue
        if rating is None and NO_SYNERGY_RE.search(first_sentence(advice)):
            continue
        claims.append(Row(hero=row.hero, cell=advice))
    return claims


# {(low id, high id): (score, note)}
type Pairs = dict[tuple[int, int], tuple[int, str]]


def pair_up(claims_by_hero: Mapping[str, Sequence[Row]],
            hero_ids: Mapping[str, int]) -> tuple[Pairs, list[str]]:
    """Claims per hero -> ({(low id, high id): (score, note)}, unresolved names).

    claims_by_hero is {hero name: [Row(teammate name, advice)]}; hero_ids is
    {name_key: hero_id}. The note comes from an article whose first sentence
    fits uncut when there is one, else from the first article by hero name.
    """
    stated: dict[tuple[int, int], dict[int, str]] = {}
    unmatched: list[str] = []
    for hero in sorted(claims_by_hero):
        hero_id = hero_ids[name_key(hero)]
        for teammate, advice in claims_by_hero[hero]:
            other_id = hero_ids.get(hero_key(teammate))
            if other_id is None:
                unmatched.append("%s: %s" % (hero, teammate))
            elif other_id != hero_id:
                pair = (min(hero_id, other_id), max(hero_id, other_id))
                stated.setdefault(pair, {}).setdefault(hero_id, advice)

    pairs: Pairs = {}
    for pair, advice_by_hero in stated.items():
        notes = list(advice_by_hero.values())
        uncut = [n for n in notes if clause(n) == first_sentence(n)]
        pairs[pair] = (len(advice_by_hero), clause((uncut or notes)[0]))
    return pairs, unmatched


# --- store ---------------------------------------------------------------------

class SynergiesSummary(ArticlePullSummary):
    synergies: int
    mutual: int
    articles: int
    unpaired: list[str]
    unmatched: list[str]


def run(connection: psycopg.Connection, pull: fetch.PullContext) -> SynergiesSummary:
    """Reload synergies from the Team Synergy column of every released hero's
    article -> the pairs stored, the mutual ones and the heroes left unpaired."""
    cursor = connection.cursor()
    released, articles = released_articles(cursor, pull)
    claims = {name: parse_synergies(text) for name, text in articles.found.items()}
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
    pull.log("  synergies  %d pairs (%d mutual) from %d articles; %d heroes unpaired" % (
        len(pairs), mutual, sum(1 for c in claims.values() if c), len(unpaired)))
    return {"synergies": len(pairs), "mutual": mutual,
            "articles": sum(1 for c in claims.values() if c),
            "unpaired": unpaired, "unmatched": unmatched, "missing": articles.missing,
            "tables": ["synergies"]}
