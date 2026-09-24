"""overwatch.fandom.com - the Overwatch Wiki: page to table.

    heroes         hero kits via the Cargo Abilities table: weapons and
                   firing configs, abilities, perks, stats, keywords
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
rate-limits. This module is that client, and the `sources` row its pages
become.
"""

import json
import os
import re
import time
from collections.abc import Sequence
from typing import Any

import requests

from db import Source
from db.data.fetch import is_stale, keep_stale

WIKI_API = "https://overwatch.fandom.com/api.php"
CARGO_PAGE_SIZE = 500
CARGO_RETRIES = 6

# The sources row this module's pages become.
WIKI = Source("wiki", "Overwatch Wiki", "https://overwatch.fandom.com/")
REQUEST_DELAY = 0.5


class WikiError(Exception):
    pass


# One Cargo row as the API's JSON gives it: {field name: value}.
CargoRow = dict[str, Any]


def cargo_query(
        session: requests.Session, table: str, fields: Sequence[str],
        cache_dir: str | None) -> list[CargoRow]:
    """Every row of a Cargo table, paginated.

    Cargo exposes the wiki's structured data directly, which is far steadier
    than parsing article templates. The endpoint rate-limits, so this backs off
    and caches the whole result.
    """
    cache_path = None
    if cache_dir:
        cache_path = os.path.join(cache_dir, "cargo_%s.json" % table.lower())
        if os.path.exists(cache_path) and not is_stale(cache_path):
            with open(cache_path, encoding="utf-8") as handle:
                return json.load(handle)
    try:
        rows = _cargo_pages(session, table, fields)
    except (WikiError, requests.RequestException) as error:
        if cache_path and os.path.exists(cache_path):
            return json.loads(keep_stale(cache_path, error))
        raise

    if cache_path:
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False)
    return rows


def _cargo_pages(session: requests.Session, table: str, fields: Sequence[str]) -> list[CargoRow]:
    rows: list[CargoRow] = []
    offset = 0
    while True:
        payload: dict[str, Any] | None = None
        for attempt in range(CARGO_RETRIES):
            response = session.get(
                WIKI_API,
                params={
                    "action": "cargoquery",
                    "tables": table,
                    "fields": ",".join(fields),
                    "limit": str(CARGO_PAGE_SIZE),
                    "offset": str(offset),
                    "format": "json",
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            error = payload.get("error", {}).get("info", "")
            if "rate limit" in error.lower():
                time.sleep(20 * (attempt + 1))
                payload = None
                continue
            if error:
                raise WikiError("%s: %s" % (table, error))
            break
        if payload is None:
            raise WikiError("%s: rate limited after %d attempts" % (table, CARGO_RETRIES))

        batch = [row["title"] for row in payload.get("cargoquery", [])]
        rows.extend(batch)
        if len(batch) < CARGO_PAGE_SIZE:
            break
        offset += CARGO_PAGE_SIZE
        time.sleep(REQUEST_DELAY * 4)
    return rows


def fetch_wikitext(session: requests.Session, title: str, cache_dir: str | None) -> str:
    """Raw wikitext of one article, cached so reruns don't re-hit the wiki."""
    cache_path = None
    if cache_dir:
        name = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_") + ".wikitext"
        cache_path = os.path.join(cache_dir, name)
        if os.path.exists(cache_path) and not is_stale(cache_path):
            with open(cache_path, encoding="utf-8") as handle:
                return handle.read()

    try:
        response = session.get(
            WIKI_API,
            params={"action": "parse", "page": title, "prop": "wikitext",
                    "format": "json"},
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise WikiError("%s: %s" % (title, payload["error"].get("info", "not found")))
        text = payload["parse"]["wikitext"]["*"]
    except (WikiError, requests.RequestException) as error:
        if cache_path and os.path.exists(cache_path):
            return keep_stale(cache_path, error)
        raise

    if cache_path:
        with open(cache_path, "w", encoding="utf-8") as handle:
            handle.write(text)
    time.sleep(REQUEST_DELAY)
    return text
