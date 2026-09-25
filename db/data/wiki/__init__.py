"""overwatch.fandom.com - the Overwatch Wiki: page to table.

Page to table, each ends in run(connection, pull):

    heroes          hero kits via the Cargo Abilities table: weapons and
                    firing configs, abilities, perks, stats, keywords; the
                    announced heroes. kits/ reads and stores its kits
    maps            maps, game modes and stages from the Maps article
    terrain         the ground each map article describes - chokes,
                    interiors, high ground, flanks, sightlines, open ground,
                    hazards, cover - counted per map and per stage
                    (pull_terrain, after maps)
    matchups        who answers whom (counters), from each hero article's
                    Match-Up column
    patches         game versions from the Patches cargo table
    playstyles      the team-composition playstyles (dive, brawl, poke)
    seasons         the seasons that have started, from the Season pages
    synergies       pairs that work together, from the same section's
                    Synergy column

The heroes pull's kit pipeline, no run():

    kits/           each hero's kit: read from its Cargo rows and its
                    article, its stats, weapons and modifiers parsed, stored

The readers the loaders share, no run():

    markup          reading the wiki's two markups - Cargo's rendered HTML
                    and article wikitext - and the tidying both need
    matchup_tables  a hero article's Match-Ups and Team Synergy section:
                    one column of its tables as rows, in either markup,
                    and a cell as plain text; synergies and matchups read it

The article HTML sits behind a bot challenge; the only open path is the
MediaWiki endpoint below, which returns JSON (Cargo) and raw wikitext and
rate-limits. This module is that client, run on db.data.fetch's request
loop and page cache at the pace of its two policies (CARGO_POLICY,
ARTICLE_POLICY), and the `sources` row its pages become.
fetch_articles is how a pull reads one article per entity: an article that
will not fetch is recorded by name and the rest are read.
"""

import json
from collections.abc import Iterable, Sequence
from typing import NamedTuple

import requests

from db import Source
from db.data.fetch import (
    FetchError,
    PullContext,
    RateLimitError,
    RequestPolicy,
    cache_key,
    cached,
    request,
)

WIKI_HOST = "https://overwatch.fandom.com"
WIKI_API = WIKI_HOST + "/api.php"
CARGO_PAGE_SIZE = 500

# The sources row this module's pages become.
WIKI = Source(code="wiki", name="Overwatch Wiki", url=WIKI_HOST + "/")

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


def cargo_query(pull: PullContext, table: str, fields: Sequence[str]) -> list[dict[str, str]]:
    """Every row of a Cargo table, paginated.

    Cargo exposes the wiki's structured data directly, which is far steadier
    than parsing article templates. The endpoint rate-limits, so CARGO_POLICY
    waits it out, and the whole result is cached as one file.
    """
    rows: list[dict[str, str]] = json.loads(cached(
        pull, cache_key("cargo", table.lower()) + ".json",
        lambda: json.dumps(_cargo_pages(pull.session, table, fields), ensure_ascii=False)))
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


def fetch_wikitext(pull: PullContext, title: str) -> str:
    """Raw wikitext of one article, cached so reruns don't re-hit the wiki."""
    return cached(pull, cache_key(title) + ".wikitext", lambda: request(
        pull.session, WIKI_API,
        {"action": "parse", "page": title, "prop": "wikitext", "format": "json"},
        ARTICLE_POLICY, lambda response: _wikitext(response, title)))


class Articles(NamedTuple):
    """What fetch_articles read: {title: wikitext} for each title that
    fetches, in order, and 'title: error' for each that would not."""
    found: dict[str, str]
    missing: list[str]


def fetch_articles(pull: PullContext, titles: Iterable[str]) -> Articles:
    """Every title's wikitext -> Articles: the ones that fetch, and the ones
    that raise FetchError - a WikiError, or a request that failed - each
    logged as it happens. Every per-article loop reads through this one
    guard."""
    found: dict[str, str] = {}
    missing: list[str] = []
    for title in titles:
        try:
            found[title] = fetch_wikitext(pull, title)
        except FetchError as error:
            missing.append("%s: %s" % (title, error))
            pull.log("  %-22s %s" % (title, error))
    return Articles(found, missing)
