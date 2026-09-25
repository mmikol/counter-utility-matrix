"""A hero's wiki article: what it adds to the Cargo kit, and an announcement.

A few Template:Ability details parameters are never registered as Cargo
fields - the interaction flags among them - so they are read off the
article wikitext and merged into the kit where Cargo left them empty. The
same article's infobox carries the hero's health pool, which Blizzard does
not publish, and for a hero marked {{Upcoming}}, its role, subrole and
release day. Its 6v6 kit is six_a_side's, read off the same fetch.
"""

import datetime
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import NamedTuple

from db import ROLES
from db.data.fetch import PullContext
from db.data.names import ability_key
from db.data.wiki import Articles, fetch_articles, markup
from db.data.wiki.kits.kit_rows import HeroKit
from db.data.wiki.kits.six_a_side import SixKit, parse_six_a_side, with_stats


class HeroProfile(NamedTuple):
    """A hero's pools from its infobox, each None when it gives none."""
    health: int | None
    shield: int | None
    armor: int | None


class Announcement(NamedTuple):
    """An upcoming hero's role, subrole and release day, from its article;
    the day is None where the article gives none. Its pools are the
    HeroProfile's."""
    role: str
    subrole: str
    release_date: datetime.date | None


# {ability key: {stat code: value}} - what an article adds to the Cargo kit.
type ExtraStats = dict[str, dict[str, str]]


def parse_hero_profile(text: str) -> HeroProfile | None:
    """{health, shield, armor} for one hero, from its infobox; None without one.

    Blizzard publishes no hero health at all, and the wiki keeps it on the
    article rather than in a Cargo table, so it comes from the same page fetch
    the stat supplement already makes.
    """
    params = _infobox(text)
    if params is None:
        return None
    return HeroProfile(health=_pool(params, "health"), shield=_pool(params, "shield"),
                       armor=_pool(params, "armor"))


def _infobox(text: str) -> dict[str, str] | None:
    """The parameters of an article's character infobox; None without one."""
    block = next(markup.find_templates(text, r"Infobox character"), None)
    return markup.parse_params(block) if block is not None else None


def _pool(params: dict[str, str], field: str) -> int | None:
    """An infobox's number for one pool, or None when it gives none."""
    digits = re.match(r"\s*(\d+)", markup.wikitext_to_text(params.get(field, "")))
    return int(digits.group(1)) if digits else None


UPCOMING_RE = re.compile(r"\{\{\s*Upcoming\s*\}\}", re.I)
# "... set to release in Season 5 on October 6, 2026": markup.DATE's groups
RELEASE_RE = re.compile(r"release[^.]{0,80}?\bon\s+%s" % markup.DATE)


def parse_announcement(text: str) -> Announcement | None:
    """An article marked {{Upcoming}} -> {role, subrole, release_date} from
    its infobox and its release sentence; None for a released hero (no
    marker) or an infobox without a role."""
    if not UPCOMING_RE.search(text or ""):
        return None
    params = _infobox(text)
    if params is None:
        return None
    role = markup.wikitext_to_text(params.get("role", "")).strip().lower()
    subrole = markup.wikitext_to_text(params.get("sub-role", "")).strip().lower()
    if role not in ROLES:
        return None
    released = RELEASE_RE.search(markup.wikitext_to_text(text))
    release_date = markup.parse_date(released.groups(), released.group(5)) if released else None
    return Announcement(role=role, subrole=subrole, release_date=release_date)


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


def supplement_from_wikitext(text: str) -> tuple[ExtraStats, HeroProfile | None]:
    """One hero's article -> ({ability key: {stat: value}}, its HeroProfile or
    None)."""
    extra: ExtraStats = {}
    for block in markup.find_templates(text, r"Ability[ _]details"):
        params = markup.parse_params(block)
        name = markup.wikitext_to_text(params.get("ability_name", ""))
        if not name or RETIRED_BLOCK_RE.search(name):
            continue
        stats: dict[str, str] = {}
        for code in SUPPLEMENT_FIELDS:
            # a citation is not part of the value
            value = markup.wikitext_to_text(markup.REF_RE.sub("", params.get(code, "")))
            if value:
                stats[code] = value
        if stats:
            extra[ability_key(name)] = stats
    return extra, parse_hero_profile(text)


class Supplement(NamedTuple):
    """What the hero articles added: each hero's pools, the stats merged into
    the kits, the articles read - each hero's wikitext, and 'hero: error'
    for each that would not fetch - and each hero's 6v6 kit, where its
    article states one."""
    profiles: dict[str, HeroProfile]
    stats: int
    articles: Articles
    six: Mapping[str, SixKit] = MappingProxyType({})


def supplement_kits(pull: PullContext, by_hero: dict[str, HeroKit]) -> Supplement:
    """Read every hero's article, merge the stats it adds into the kit in
    place where Cargo left them empty, and keep the hero's pools, its 6v6
    kit with each line's stat named from the merged rows, and the articles.
    A hero whose article will not fetch keeps its Cargo kit and is recorded
    as missing."""
    articles = fetch_articles(pull, sorted(by_hero))
    profiles: dict[str, HeroProfile] = {}
    six: dict[str, SixKit] = {}
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
        said = parse_six_a_side(text)
        if said.pools or said.lines or said.rejected:
            pieces = {ability_key(entry["name"]): entry["stats"]
                      for entry in by_hero[hero_name].entries()}
            six[hero_name] = with_stats(said, pieces)
    return Supplement(profiles, stats, articles, six)
