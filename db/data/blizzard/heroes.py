"""Pull + clean + store: overwatch.blizzard.com - the roster.

The roster page carries every hero's role, subrole and portrait, and the
role and subrole filter icons; each hero page carries an abilities carousel
and a perks section. Blizzard publishes prose only - no
numbers, no map data - and omits some abilities outright, so weapons,
stats, the missing abilities and the maps come from the wiki.
"""

import re
from datetime import datetime
from typing import TypedDict

import psycopg
from bs4 import BeautifulSoup, Tag

from db import PERK_TIERS, psql
from db.data import ArticlePullSummary, fetch
from db.data.blizzard import BASE_URL, BLIZZARD, HEROES_URL, attr
from db.data.fetch import cache_key, cached_get

# One host serves every page. A keep-alive socket it drops fails one request,
# and a retry on a fresh connection saves the pull.
PAGE_POLICY = fetch.RequestPolicy(attempts=3)

# --- extract: markup -> Python ---------------------------------------------

class Subrole(TypedDict):
    code: str
    role_code: str
    name: str
    passive_description: str


class RoleIcons(TypedDict):
    roles: dict[str, str]           # code -> icon url
    subroles: dict[str, str]


class RosterHero(TypedDict):
    slug: str
    name: str
    role_code: str
    subrole_code: str
    portrait_url: str | None


class AbilityText(TypedDict):
    name: str
    description: str
    position: int


class PerkText(TypedDict):
    tier_id: int
    name: str
    description: str
    position: int


def node_text(node: Tag) -> str:
    """Plain gameplay text from a BeautifulSoup node. It decomposes the
    node's <img> tags in place: the tree loses them for every later reader.

    Ability descriptions embed input-icon <img> tags mid-sentence and wrap
    numbers in coloured <span>s. Both are dropped: the schema stores gameplay
    text, not markup or media. db.data.wiki.markup.html_to_text is the wiki's
    reader of a string; this one reads a parsed node.
    """
    for image in node.find_all("img"):
        image.decompose()
    return " ".join(node.get_text(" ", strip=True).split())


URL_IN_STYLE_RE = re.compile(r"url\((['\"]?)(.*?)\1\)")


class ScrapeError(Exception):
    pass


def _style_url(node: Tag) -> str | None:
    match = URL_IN_STYLE_RE.search(attr(node, "style") if node.has_attr("style") else "")
    return match.group(2) if match else None


def parse_subroles(soup: BeautifulSoup) -> dict[str, Subrole]:
    """The ten subroles and the passive each one grants."""
    subroles: dict[str, Subrole] = {}
    for div in soup.select("div.subrole[data-role][data-subrole]"):
        spans = div.find_all("span")
        if len(spans) != 2:
            continue
        code = attr(div, "data-subrole")
        subroles[code] = {
            "code": code,
            "role_code": attr(div, "data-role"),
            # The label span reads "Tactician: ".
            "name": spans[0].get_text(strip=True).rstrip(":").strip(),
            "passive_description": node_text(spans[1]),
        }
    if not subroles:
        raise ScrapeError("no subroles found on the heroes page")
    return subroles


def parse_icons(soup: BeautifulSoup) -> RoleIcons:
    """{'roles': {code: url}, 'subroles': {code: url}} - the icons the site's
    own role and subrole filters draw. The board draws the role ones."""
    roles: dict[str, str] = {}
    subroles: dict[str, str] = {}
    for option in soup.select("option.role[data-role]"):
        url = _style_url(option)
        if url and attr(option, "data-role") != "all-heroes":
            roles[attr(option, "data-role")] = url
    for option in soup.select("option.subrole[data-subrole]"):
        url = _style_url(option)
        if url:
            subroles[attr(option, "data-subrole")] = url
    for card in soup.select("a.hero-card"):
        icon = card.find("blz-card")
        if isinstance(icon, Tag) and icon.get("icon") and card.get("data-role"):
            roles.setdefault(attr(card, "data-role"), attr(icon, "icon"))
    return {"roles": roles, "subroles": subroles}


def parse_roster(soup: BeautifulSoup) -> list[RosterHero]:
    """Every hero card: slug, name, role, subrole, portrait."""
    heroes: list[RosterHero] = []
    for card in soup.select("a.hero-card"):
        heading = card.find("h2", attrs={"slot": "heading"})
        href = attr(card, "href") if card.has_attr("href") else ""
        if heading is None or not href:
            raise ScrapeError("hero card missing a name or link: %r" % card.get("id"))
        portrait = card.find("blz-image", class_="heroCardPortrait")
        heroes.append(
            {
                "slug": href.rstrip("/").rsplit("/", 1)[-1],
                "name": heading.get_text(strip=True),
                "role_code": attr(card, "data-role"),
                "subrole_code": attr(card, "data-subrole"),
                "portrait_url": (attr(portrait, "src")
                                 if isinstance(portrait, Tag) and portrait.has_attr("src")
                                 else None),
            }
        )
    if not heroes:
        raise ScrapeError("no hero cards found on the heroes page")
    return heroes


def parse_abilities(soup: BeautifulSoup, slug: str) -> list[AbilityText]:
    """Ordered abilities for one hero. Nothing here classifies an ability:
    Blizzard labels neither weapons nor ultimates; kind_id is left NULL for
    the wiki load to fill in."""
    carousels = soup.find_all("blz-carousel")
    if len(carousels) != 1:
        raise ScrapeError("%s: expected 1 carousel, found %d" % (slug, len(carousels)))

    slides = carousels[0].find_all("blz-feature", attrs={"slot": "slide"})
    if not slides:
        raise ScrapeError("%s: no abilities found" % slug)

    abilities: list[AbilityText] = []
    for position, slide in enumerate(slides):
        heading = slide.find("h3", class_="heading")
        description = slide.find("p", attrs={"slot": "description"})
        if heading is None or description is None:
            raise ScrapeError("%s: ability slide %d is malformed" % (slug, position))
        abilities.append(
            {
                "name": heading.get_text(strip=True),
                "description": node_text(description),
                "position": position,
            }
        )
    return abilities


def parse_perks(soup: BeautifulSoup, slug: str) -> list[PerkText]:
    """The four perks: two minor (level 2) and two major (level 3).
    Stadium Powers live in their own section and are deliberately not read."""
    section = soup.find("blz-section", id="perks")
    if section is None:
        raise ScrapeError("%s: no perks section" % slug)

    perks: list[PerkText] = []
    for category in section.select("div.perk-category"):
        tier_codes = [c for c in category.get_attribute_list("class") if c in PERK_TIERS]
        if len(tier_codes) != 1:
            raise ScrapeError("%s: perk category has no tier: %r" % (slug, category.get("class")))
        tier_code = tier_codes[0]

        details = category.select("div.perk-details")
        if len(details) != 2:
            raise ScrapeError(
                "%s: expected 2 %s perks, found %d" % (slug, tier_code, len(details))
            )

        for position, detail in enumerate(details, start=1):
            heading = detail.find("h3", attrs={"slot": "subheading"})
            description = detail.find("div", attrs={"slot": "description"})
            if heading is None or description is None:
                raise ScrapeError("%s: malformed %s perk" % (slug, tier_code))
            perks.append(
                {
                    "tier_id": PERK_TIERS[tier_code],
                    "name": heading.get_text(strip=True),
                    "description": node_text(description),
                    "position": position,
                }
            )

    if len(perks) != 4:
        raise ScrapeError("%s: expected 4 perks, found %d" % (slug, len(perks)))
    return perks


# --- store ---------------------------------------------------------------------

ROLE_NAMES = {"tank": "Tank", "damage": "Damage", "support": "Support"}


def _store(
        cursor: psycopg.Cursor, subroles: dict[str, Subrole], heroes: list[RosterHero],
        abilities_by_slug: dict[str, list[AbilityText]], perks_by_slug: dict[str, list[PerkText]],
        icons: RoleIcons, cao: datetime) -> None:
    """Upsert the roles, subroles, heroes and each hero's abilities and perks."""
    source_id = psql.register_source(cursor, BLIZZARD, cao)

    role_ids: dict[str, int] = {}
    for code in ("tank", "damage", "support"):
        cursor.execute(
            "INSERT INTO roles (code, name, icon_url, source_id)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
            " icon_url = coalesce(EXCLUDED.icon_url, roles.icon_url),"
            " source_id = EXCLUDED.source_id, cao = now()"
            " RETURNING role_id",
            (code, ROLE_NAMES[code], icons["roles"].get(code), source_id),
        )
        role_ids[code] = psql.scalar(cursor)

    subrole_ids: dict[str, int] = {}
    for subrole in sorted(subroles.values(), key=lambda s: (s["role_code"], s["code"])):
        cursor.execute(
            "INSERT INTO subroles (role_id, code, name, passive_description,"
            " icon_url, source_id) VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (code) DO UPDATE SET role_id = EXCLUDED.role_id,"
            " name = EXCLUDED.name,"
            " passive_description = EXCLUDED.passive_description,"
            " icon_url = coalesce(EXCLUDED.icon_url, subroles.icon_url),"
            " source_id = EXCLUDED.source_id, cao = now()"
            " RETURNING subrole_id",
            (
                role_ids[subrole["role_code"]],
                subrole["code"],
                subrole["name"],
                subrole["passive_description"],
                icons["subroles"].get(subrole["code"]),
                source_id,
            ),
        )
        subrole_ids[subrole["code"]] = psql.scalar(cursor)

    for hero in heroes:
        cursor.execute(
            "INSERT INTO heroes (slug, name, role_id, subrole_id, portrait_url,"
            " source_id) VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name,"
            " role_id = EXCLUDED.role_id, subrole_id = EXCLUDED.subrole_id,"
            " portrait_url = coalesce(EXCLUDED.portrait_url, heroes.portrait_url),"
            " status = 'released',"          # Blizzard listing a hero is the release
            " source_id = EXCLUDED.source_id, cao = now()"
            " RETURNING hero_id",
            (
                hero["slug"],
                hero["name"],
                role_ids[hero["role_code"]],
                subrole_ids[hero["subrole_code"]],
                hero["portrait_url"],
                source_id,
            ),
        )
        hero_id = psql.scalar(cursor)

        for ability in abilities_by_slug.get(hero["slug"], ()):
            cursor.execute(
                # Upserting by name means a RENAMED ability collides with its
                # own old row on (hero_id, position) and fails the stage. That
                # is deliberate: an update refreshes values, and a structural
                # change to a kit is what `rebuild` is for.
                "INSERT INTO abilities (hero_id, name, description, position,"
                " source_id) VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (hero_id, name) DO UPDATE SET"
                " description = EXCLUDED.description,"
                " position = EXCLUDED.position,"
                " source_id = EXCLUDED.source_id, cao = now()",
                (hero_id, ability["name"], ability["description"],
                 ability["position"], source_id),
            )
        for perk in perks_by_slug.get(hero["slug"], ()):
            cursor.execute(
                "INSERT INTO perks (hero_id, tier_id, name, description, position,"
                " source_id) VALUES (%s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (hero_id, name) DO UPDATE SET"
                " tier_id = EXCLUDED.tier_id,"
                " description = EXCLUDED.description,"
                " position = EXCLUDED.position,"
                " source_id = EXCLUDED.source_id, cao = now()",
                (hero_id, perk["tier_id"], perk["name"], perk["description"],
                 perk["position"], source_id),
            )


class HeroesSummary(ArticlePullSummary):
    heroes: int
    subroles: int
    abilities: int
    perks: int
    portraits: int


def run(connection: psycopg.Connection, pull: fetch.PullContext) -> HeroesSummary:
    """Store the roster and every hero page's ability and perk text, in one
    transaction -> the heroes, subroles, abilities, perks and portraits, and
    the hero pages that would not fetch (missing): those heroes are stored
    from the roster and keep the text they had."""
    roster_soup = BeautifulSoup(
        cached_get(pull, HEROES_URL, cache_key(HEROES_URL), policy=PAGE_POLICY),
        "html.parser")
    subroles = parse_subroles(roster_soup)
    heroes = parse_roster(roster_soup)
    icons = parse_icons(roster_soup)
    pull.log("roster: %d heroes, %d subroles" % (len(heroes), len(subroles)))

    abilities_by_slug: dict[str, list[AbilityText]] = {}
    perks_by_slug: dict[str, list[PerkText]] = {}
    missing: list[str] = []
    for index, hero in enumerate(heroes, start=1):
        slug = hero["slug"]
        try:
            page = cached_get(pull, "%s/heroes/%s/" % (BASE_URL, slug), cache_key(slug),
                              policy=PAGE_POLICY)
        except fetch.FetchError as error:
            # the hero is still stored from the roster; its text stays as it was
            missing.append("%s: %s" % (hero["name"], error))
            pull.log("  [%2d/%d] %-18s %s" % (index, len(heroes), hero["name"], error))
            continue
        soup = BeautifulSoup(page, "html.parser")
        abilities_by_slug[slug] = parse_abilities(soup, slug)
        perks_by_slug[slug] = parse_perks(soup, slug)
        pull.log("  [%2d/%d] %-18s %d abilities, %d perks" % (
            index, len(heroes), hero["name"],
            len(abilities_by_slug[slug]), len(perks_by_slug[slug])))

    cursor = connection.cursor()
    _store(cursor, subroles, heroes, abilities_by_slug, perks_by_slug, icons, psql.now())
    connection.commit()
    return {
        "heroes": len(heroes),
        "subroles": len(subroles),
        "abilities": sum(len(a) for a in abilities_by_slug.values()),
        "perks": sum(len(p) for p in perks_by_slug.values()),
        "portraits": sum(1 for h in heroes if h["portrait_url"]),
        "missing": missing,
        "tables": ["roles", "subroles", "heroes", "abilities", "perks"],
    }
