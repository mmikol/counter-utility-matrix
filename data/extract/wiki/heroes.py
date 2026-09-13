"""Extracting hero kit from the wiki's Cargo Abilities table.

One Cargo row per ability, with every stat as its own column, an explicit
`removed` flag for retired kit, and an `ability_key` naming the input slot.
Rows come back alphabetically, so weapons are sorted by firing slot here -
grouping them into weapons is the transform stage's job.
"""

import re

from data.extract.wiki import markup

# Columns that describe the ability rather than measure it.
NON_STAT_FIELDS = frozenset(
    {"hero_name", "ability_name", "ability_type", "ability_key", "removed",
     "official_description", "ability_keywords"}
)

STAT_ALIASES = {"range_distance": "range"}

WEAPON_KIND, ABILITY_KIND, ULTIMATE_KIND, PASSIVE_KIND = 1, 2, 3, 4

# Cargo returns rows alphabetically, but weapon grouping needs firing order.
SLOT_RANK = {
    "primary fire": 0, "hip fire": 0,
    "secondary fire": 1, "ads": 1,
}


def slot_rank(entry):
    for token in (entry["mode"], entry["input_key"]):
        rank = SLOT_RANK.get((token or "").strip().lower())
        if rank is not None:
            return rank
    return 2


def ability_kind(base_type):
    lowered = base_type.lower()
    if lowered.startswith("weapon"):
        return WEAPON_KIND
    if "ultimate" in lowered:
        return ULTIMATE_KIND
    if "passive" in lowered:
        return PASSIVE_KIND
    return ABILITY_KIND


def parse_rows(rows):
    """Cargo rows -> {hero_name: (weapons, abilities, perks)}."""
    heroes = {}
    for row in rows:
        # Cargo returns field names with spaces.
        fields = {key.replace(" ", "_"): value for key, value in row.items()}

        if (fields.get("removed") or "").strip():
            continue  # retired kit
        hero_name = (fields.get("hero_name") or "").strip()
        name = markup.html_to_text(fields.get("ability_name"))
        if not hero_name or not name:
            continue

        base_type, mode = markup.split_type(
            markup.html_to_text(fields.get("ability_type"))
        )
        if not base_type:
            continue

        stats = {}
        for key, raw in fields.items():
            if key in NON_STAT_FIELDS or not raw:
                continue
            code = STAT_ALIASES.get(key, key)
            value = markup.html_to_text(raw)
            if value:
                stats[code] = (value, None, raw)

        entry = {
            "name": name,
            "mode": mode,
            "input_key": markup.html_to_text(fields.get("ability_key")) or None,
            "keywords": markup.html_to_text(fields.get("ability_keywords")) or "",
            "description": markup.html_to_text(fields.get("official_description")),
            "stats": stats,
        }

        weapons, abilities, perks = heroes.setdefault(hero_name, ([], [], []))
        if "perk" in base_type.lower():
            perks.append(entry)
        elif base_type.lower().startswith("weapon"):
            entry["kind_id"] = WEAPON_KIND
            entry["weapon_type"] = (stats.get("shot_type", ("", None, ""))[0]
                                    .split(";")[0].strip().lower() or None)
            entry["display_name"] = name
            weapons.append(entry)
        else:
            entry["kind_id"] = ability_kind(base_type)
            entry["display_name"] = name
            abilities.append(entry)

    for weapons, _, _ in heroes.values():
        weapons.sort(key=slot_rank)
    return heroes


def parse_hero_profile(text):
    """{health, shield, armor} for one hero, from its infobox.

    Blizzard publishes no hero health at all, and the wiki keeps it on the
    article rather than in a Cargo table, so it comes from the same page fetch
    the stat supplement already makes.
    """
    for block in markup.find_templates(text, r"Infobox character"):
        params = markup.parse_params(block)
        profile = {}
        for field in ("health", "shield", "armor"):
            value = markup.wikitext_to_text(params.get(field, ""))
            digits = re.match(r"\s*(\d+)", value)
            profile[field] = int(digits.group(1)) if digits else None
        return profile
    return {}
