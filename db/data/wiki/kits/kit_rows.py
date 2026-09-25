"""The wiki's Cargo Abilities rows, read into each hero's kit.

The table has one row per ability: every stat as its own column, an explicit
`removed` flag for retired kit, an `ability_key` naming the input slot and a
keyword list ("hitscan", "strong movement", "stun", "lesser cleanse", ...).
A row becomes a weapon's firing mode, an ability or a perk by its
ability_type ("Weapon;;Hip Fire", "Ultimate Ability", "Major Perk"), which
split_type unpicks into the base type and the firing mode packed in with
it, and each kind of entry is a TypedDict that holds the keys its kind
guarantees. Rows come back alphabetically; weapons.py, which owns the
firing modes, puts the weapon entries in firing order and groups them into
weapons.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Literal, NamedTuple, TypedDict

from db import KIND_ABILITY, KIND_PASSIVE, KIND_ULTIMATE, KIND_WEAPON
from db.data.wiki import markup


class KitEntry(TypedDict):
    """What every Cargo row reads into: a weapon's firing mode, an ability or
    a perk."""
    name: str
    mode: str | None
    input_key: str | None
    keywords: str
    description: str
    stats: dict[str, str]       # stat code -> its value's clean text


class PerkEntry(KitEntry):
    tier: Literal["minor", "major"]


class AbilityEntry(KitEntry):
    kind: str                   # a code from db.ABILITY_KINDS


class WeaponEntry(KitEntry):
    display_name: str           # the name stored; weapons.py renames an ADS config
    weapon_type: str | None     # the shot type: "hitscan", "projectile", ...


class HeroKit(NamedTuple):
    """One hero's kit, each list in Cargo's order, which is alphabetical;
    group_weapons sorts the weapons into firing order as the store groups
    them."""
    weapons: list[WeaponEntry]
    abilities: list[AbilityEntry]
    perks: list[PerkEntry]

    def entries(self) -> list[KitEntry]:
        """Every entry of the kit: the weapons, the abilities, the perks."""
        return [*self.weapons, *self.abilities, *self.perks]


# Columns that describe the ability rather than measure it.
NON_STAT_FIELDS = frozenset(
    {
        "hero_name", "ability_name", "ability_type", "ability_key", "removed",
        "official_description", "ability_keywords"
    }
)

STAT_ALIASES = {"range_distance": "range"}


# "Weapon;;Hip Fire" and "Weapon (Hip Fire)" mean the same thing; the wiki uses
# both. "Ultimate Ability (Mech)" and "Ultimate Ability;;Mech" likewise.
TYPE_SPLIT_RE = re.compile(r"^(.*?)\s*(?:;;\s*(.+)|\(([^)]*)\))\s*$")


class AbilityType(NamedTuple):
    """A Cargo ability type unpicked: the base type, and the firing mode
    packed in with it or None."""
    base: str
    mode: str | None


def split_type(ability_type: str | None) -> AbilityType:
    """'Weapon;;Hip Fire' -> AbilityType('Weapon', 'Hip Fire'). No suffix ->
    the type and None."""
    text = (ability_type or "").strip()
    match = TYPE_SPLIT_RE.match(text)
    if not match:
        return AbilityType(text, None)
    mode = (match.group(2) or match.group(3) or "").strip() or None
    return AbilityType(match.group(1).strip(), mode)


def ability_kind(base_type: str) -> str:
    """The wiki's ability_type -> a code from the shared vocabulary. The kind_id
    behind it comes from the ability_kinds table at write time, so the parser
    never has to know the numbers."""
    lowered = base_type.lower()
    if lowered.startswith("weapon"):
        return KIND_WEAPON
    if "ultimate" in lowered:
        return KIND_ULTIMATE
    if "passive" in lowered:
        return KIND_PASSIVE
    return KIND_ABILITY


def _stats(fields: Mapping[str, str]) -> dict[str, str]:
    """Every measuring column a row fills, by stat code: its clean text."""
    stats: dict[str, str] = {}
    for key, raw in fields.items():
        if key in NON_STAT_FIELDS or not raw:
            continue
        value = markup.html_to_text(raw)
        if value:
            stats[STAT_ALIASES.get(key, key)] = value
    return stats


def _weapon_type(fields: Mapping[str, str]) -> str | None:
    """A weapon's shot type: the first of the shot_type column's values."""
    shot_type = markup.html_to_text(fields.get("shot_type"))
    return shot_type.split(";")[0].strip().lower() or None


def _entry(fields: Mapping[str, str], name: str, mode: str | None) -> KitEntry:
    """What every kind of entry reads off its row."""
    return KitEntry(
        name=name,
        mode=mode,
        input_key=markup.html_to_text(fields.get("ability_key")) or None,
        keywords=markup.html_to_text(fields.get("ability_keywords")),
        description=markup.html_to_text(fields.get("official_description")),
        stats=_stats(fields),
    )


def parse_kits(rows: Iterable[Mapping[str, str]]) -> dict[str, HeroKit]:
    """Cargo rows -> {hero_name: HeroKit(weapons, abilities, perks)}."""
    heroes: dict[str, HeroKit] = {}
    for row in rows:
        # Cargo returns field names with spaces.
        fields = {key.replace(" ", "_"): value for key, value in row.items()}

        if (fields.get("removed") or "").strip():
            continue  # retired kit
        hero_name = (fields.get("hero_name") or "").strip()
        name = markup.html_to_text(fields.get("ability_name"))
        if not hero_name or not name:
            continue

        ability_type = split_type(markup.html_to_text(fields.get("ability_type")))
        if not ability_type.base:
            continue

        base = _entry(fields, name, ability_type.mode)
        kit = heroes.setdefault(hero_name, HeroKit([], [], []))
        lowered = ability_type.base.lower()
        if "perk" in lowered:
            kit.perks.append(PerkEntry(**base, tier="major" if "major" in lowered else "minor"))
            continue
        kind = ability_kind(ability_type.base)
        if kind == KIND_WEAPON:
            kit.weapons.append(WeaponEntry(**base, display_name=name,
                                           weapon_type=_weapon_type(fields)))
        else:
            kit.abilities.append(AbilityEntry(**base, kind=kind))
    return heroes
