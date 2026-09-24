"""overwatch.fandom.com - the Overwatch Wiki: page to table.

    heroes         hero kits via the Cargo Abilities table: weapons and
                   firing configs, abilities, perks, stats, keywords; the
                   announced heroes
    kit_rows       a Cargo Abilities row -> a typed weapon, ability or perk
                   entry of one hero's kit
    hero_articles  a hero's article -> the stats Cargo lacks, the health
                   pool, an announcement
    kit_store      the kits into the tables
    maps           maps, game modes and stages from the Maps article
    patches        game versions from the Patches cargo table
    playstyles     the team-composition playstyles (dive, brawl, poke)
    seasons        the seasons that have started, from the Season pages
    synergies      pairs that work together, from each hero article's
                   Synergy column
    matchups       who answers whom (counters), from the same section's
                   Match-Up column
    markup         reading the wiki's two markups - Cargo's rendered HTML
                   and article wikitext - and the tidying both need
    measurements   a stat value -> value, unit, window, condition
    weapons        firing modes grouped into weapons
    modifiers      buff direction and target, off the keywords

The article HTML sits behind a bot challenge; the only open path is the
MediaWiki endpoint below, which returns JSON (Cargo) and raw wikitext and
rate-limits. This module is that client, run on db.data.fetch's request
loop and page cache, and the `sources` row its pages become.
fetch_articles is how a pull reads one article per entity: an article that
will not fetch is recorded by name and the rest are read.
"""

import json
from collections.abc import Callable, Iterable, Sequence

import requests

from db import Source
from db.data.fetch import (
    FetchError,
    RateLimitError,
    RequestPolicy,
    cache_key,
    cached,
    request,
)

WIKI_API = "https://overwatch.fandom.com/api.php"
CARGO_PAGE_SIZE = 500

# The sources row this module's pages become.
WIKI = Source("wiki", "Overwatch Wiki", "https://overwatch.fandom.com/")

# Cargo is a handful of paged requests, so it waits out a rate limit or a
# failed request: 20, 40, 60, 60 and 60 s, then gives up. 2 s between pages.
CARGO_POLICY = RequestPolicy(attempts=6, backoff=20.0, timeout=60, delay=2.0)
# An article is asked for once. A refresh reads some 200 of them, and one
# that fails keeps its cached copy or is missing until the next refresh;
# retrying each against a down wiki would outlast the refresh.
ARTICLE_POLICY = RequestPolicy(attempts=1, timeout=40, delay=0.5)


class WikiError(FetchError):
    """The wiki answered, but not with what was asked for."""


def _payload(response: requests.Response, name: str) -> dict[str, object]:
    """The JSON object the wiki answered with. An error it states is raised:
    a rate limit as RateLimitError, which is retried, anything else as
    WikiError."""
    payload = response.json()
    if not isinstance(payload, dict):
        raise WikiError("%s: the response is not a JSON object" % name)
    if "error" in payload:
        error = payload["error"]
        info = str(error.get("info", "")) if isinstance(error, dict) else ""
        if "rate limit" in info.lower():
            raise RateLimitError("%s: %s" % (name, info))
        raise WikiError("%s: %s" % (name, info or "not found"))
    return payload


def _cargo_rows(response: requests.Response, table: str) -> list[dict[str, str]]:
    """One page of a Cargo table: each row's fields."""
    items = _payload(response, table).get("cargoquery", [])
    if not isinstance(items, list) or not all(
            isinstance(item, dict) and isinstance(item.get("title"), dict) for item in items):
        raise WikiError("%s: a row has no title" % table)
    return [item["title"] for item in items]


def _wikitext(response: requests.Response, title: str) -> str:
    """The wikitext of one article."""
    node: object = _payload(response, title)
    for key in ("parse", "wikitext", "*"):
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, str):
        raise WikiError("%s: the response has no wikitext" % title)
    return node


def cargo_query(
        session: requests.Session, table: str, fields: Sequence[str],
        cache_dir: str | None) -> list[dict[str, str]]:
    """Every row of a Cargo table, paginated.

    Cargo exposes the wiki's structured data directly, which is far steadier
    than parsing article templates. The endpoint rate-limits, so CARGO_POLICY
    waits it out, and the whole result is cached as one file.
    """
    rows: list[dict[str, str]] = json.loads(cached(
        cache_dir, cache_key("cargo", table.lower()) + ".json",
        lambda: json.dumps(_cargo_pages(session, table, fields), ensure_ascii=False)))
    return rows


def _cargo_pages(
        session: requests.Session, table: str, fields: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    offset = 0
    while True:
        batch = request(
            session, WIKI_API,
            {
                "action": "cargoquery",
                "tables": table,
                "fields": ",".join(fields),
                "limit": str(CARGO_PAGE_SIZE),
                "offset": str(offset),
                "format": "json",
            },
            CARGO_POLICY, lambda response: _cargo_rows(response, table))
        rows.extend(batch)
        if len(batch) < CARGO_PAGE_SIZE:
            return rows
        offset += CARGO_PAGE_SIZE


def fetch_wikitext(session: requests.Session, title: str, cache_dir: str | None) -> str:
    """Raw wikitext of one article, cached so reruns don't re-hit the wiki."""
    return cached(cache_dir, cache_key(title) + ".wikitext", lambda: request(
        session, WIKI_API,
        {"action": "parse", "page": title, "prop": "wikitext", "format": "json"},
        ARTICLE_POLICY, lambda response: _wikitext(response, title)))


def fetch_articles(
        session: requests.Session, titles: Iterable[str], cache_dir: str | None,
        log: Callable[[str], None]) -> tuple[dict[str, str], list[str]]:
    """({title: wikitext} for each title that fetches, in order, ['title:
    error'] for each that raises FetchError - a WikiError, or a request that
    failed), each failure logged as it happens. Every per-article loop reads
    through this one guard."""
    articles: dict[str, str] = {}
    missing: list[str] = []
    for title in titles:
        try:
            articles[title] = fetch_wikitext(session, title, cache_dir)
        except FetchError as error:
            missing.append("%s: %s" % (title, error))
            log("  %-22s %s" % (title, error))
    return articles, missing
