"""A hero's wiki article: what it adds to the Cargo kit, and an announcement.

A few Template:Ability details parameters are never registered as Cargo
fields - the interaction flags among them - so they are read off the
article wikitext and merged into the kit where Cargo left them empty. The
same article's infobox carries the hero's health pool, which Blizzard does
not publish, and for a hero marked {{Upcoming}}, its role, subrole and
release day.
"""

import contextlib
import datetime
import re
from collections.abc import Callable
from typing import NamedTuple, TypedDict

import requests

from db.data.names import ability_key
from db.data.wiki import fetch_articles, markup
from db.data.wiki.kit_rows import HeroKit, StatValue


class HeroProfile(TypedDict):
    """A hero's pools from its infobox, each None when it gives none."""
    health: int | None
    shield: int | None
    armor: int | None


class Announcement(TypedDict):
    role: str
    subrole: str
    health: int | None
    release_date: datetime.date | None


# {ability key: {stat code: value}} - what an article adds to the Cargo kit.
ExtraStats = dict[str, dict[str, StatValue]]


def parse_hero_profile(text: str) -> HeroProfile | None:
    """{health, shield, armor} for one hero, from its infobox; None without one.

    Blizzard publishes no hero health at all, and the wiki keeps it on the
    article rather than in a Cargo table, so it comes from the same page fetch
    the stat supplement already makes.
    """
    for block in markup.find_templates(text, r"Infobox character"):
        params = markup.parse_params(block)
        return HeroProfile(health=_pool(params, "health"), shield=_pool(params, "shield"),
                           armor=_pool(params, "armor"))
    return None


def _pool(params: dict[str, str], field: str) -> int | None:
    """An infobox's number for one pool, or None when it gives none."""
    digits = re.match(r"\s*(\d+)", markup.wikitext_to_text(params.get(field, "")))
    return int(digits.group(1)) if digits else None


UPCOMING_RE = re.compile(r"\{\{\s*Upcoming\s*\}\}", re.I)
RELEASE_RE = re.compile(r"release[^.]{0,80}?\bon\s+([A-Z][a-z]+ \d{1,2}, \d{4})")


def parse_announcement(text: str) -> Announcement | None:
    """An article marked {{Upcoming}} -> {role, subrole, health, release_date}
    from its infobox and its release sentence; None for a released hero (no
    marker) or an infobox without a role."""
    if not UPCOMING_RE.search(text or ""):
        return None
    for block in markup.find_templates(text, r"Infobox character"):
        params = markup.parse_params(block)
        role = markup.wikitext_to_text(params.get("role", "")).strip().lower()
        subrole = markup.wikitext_to_text(params.get("sub-role", "")).strip().lower()
        if role not in ("tank", "damage", "support"):
            return None
        health = re.match(r"\s*(\d+)", markup.wikitext_to_text(params.get("health", "")))
        released = RELEASE_RE.search(markup.wikitext_to_text(text))
        release_date: datetime.date | None = None
        if released:
            # a date the wiki spells another way leaves release_date as it is
            with contextlib.suppress(ValueError):
                release_date = datetime.datetime.strptime(released.group(1),
                                                          "%B %d, %Y").date()
        return Announcement(role=role, subrole=subrole,
                            health=int(health.group(1)) if health else None,
                            release_date=release_date)
    return None


# Declared on Template:Ability details but not registered as Cargo fields.
# `heal` is registered, but Cargo returns it empty for some abilities
# (Mizuki's Healing Kasa); the merge fills only what Cargo left empty.
SUPPLEMENT_FIELDS = (
    "ignores_matrix", "ignores_deflect", "ignores_window", "ignores_barrier",
    "ignores_boost", "aoe", "view_angle", "heal",
)

# A retired kit's block: "Teleporter (old)". ability_key() drops the
# parenthetical, so it would overwrite the live block of the same name.
RETIRED_BLOCK_RE = re.compile(r"\(old\)\s*$", re.I)
# A citation is not part of the value.
REF_RE = re.compile(r"<ref\b[^>]*/>|<ref\b[^>]*>.*?</ref>", re.I | re.S)


def supplement_from_wikitext(text: str) -> tuple[ExtraStats, HeroProfile | None]:
    """One hero's article -> ({ability key: {stat: value}}, its HeroProfile or
    None)."""
    extra: ExtraStats = {}
    for block in markup.find_templates(text, r"Ability[ _]details"):
        params = markup.parse_params(block)
        name = markup.wikitext_to_text(params.get("ability_name", ""))
        if not name or RETIRED_BLOCK_RE.search(name):
            continue
        stats: dict[str, StatValue] = {}
        for code in SUPPLEMENT_FIELDS:
            value = markup.wikitext_to_text(REF_RE.sub("", params.get(code, "")))
            if value:
                stats[code] = StatValue(value, params[code])
        if stats:
            extra[ability_key(name)] = stats
    return extra, parse_hero_profile(text)


class Supplement(NamedTuple):
    """What the hero articles added: each hero's pools, the stats merged into
    the kits, and 'hero: error' for each article that would not fetch."""
    profiles: dict[str, HeroProfile]
    stats: int
    missing: list[str]


def supplement_kits(
        session: requests.Session, by_hero: dict[str, HeroKit], cache_dir: str | None,
        log: Callable[[str], None]) -> Supplement:
    """Read every hero's article, merge the stats it adds into the kit in
    place where Cargo left them empty, and keep the hero's pools. A hero whose
    article will not fetch keeps its Cargo kit and is recorded as missing."""
    articles = fetch_articles(session, sorted(by_hero), cache_dir, log)
    profiles: dict[str, HeroProfile] = {}
    stats = 0
    for hero_name, text in articles.found.items():
        extra, profile = supplement_from_wikitext(text)
        if profile is not None:
            profiles[hero_name] = profile
        for entry in by_hero[hero_name].entries():
            for code, value in extra.get(ability_key(entry["name"]), {}).items():
                if code not in entry["stats"]:
                    entry["stats"][code] = value
                    stats += 1
    return Supplement(profiles, stats, articles.missing)
