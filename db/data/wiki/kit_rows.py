"""The wiki's Cargo Abilities rows, read into each hero's kit.

The table has one row per ability: every stat as its own column, an explicit
`removed` flag for retired kit, an `ability_key` naming the input slot and a
keyword list ("hitscan", "strong movement", "stun", "lesser cleanse", ...).
A row becomes a weapon's firing mode, an ability or a perk by its
ability_type ("Weapon;;Hip Fire", "Ultimate Ability", "Major Perk"), and
each kind of entry is a TypedDict that holds the keys its kind guarantees.
Rows come back alphabetically, so weapons are sorted by firing slot here;
grouping them into weapons is weapons.py's job.
"""

from collections.abc import Iterable, Mapping
from typing import Literal, NamedTuple, TypedDict

from db import KIND_ABILITY, KIND_PASSIVE, KIND_ULTIMATE, KIND_WEAPON
from db.data.wiki import markup


class StatValue(NamedTuple):
    """A stat's value: its clean text, and the wiki's raw markup it was read from."""
    text: str
    raw: str


class KitEntry(TypedDict):
    """What every Cargo row reads into: a weapon's firing mode, an ability or
    a perk."""
    name: str
    mode: str | None
    input_key: str | None
    keywords: str
    description: str
    stats: dict[str, StatValue]


class PerkEntry(KitEntry):
    tier: Literal["minor", "major"]


class AbilityEntry(KitEntry):
    kind: str                   # a code from db.ABILITY_KINDS
    display_name: str           # the name stored; weapons.py renames an ADS config


class WeaponEntry(AbilityEntry):
    weapon_type: str | None     # the shot type: "hitscan", "projectile", ...


class HeroKit(NamedTuple):
    """One hero's kit, each list in the order the pull stores it."""
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


# Cargo returns rows alphabetically, but weapon grouping needs firing order.
SLOT_RANK = {
    "primary fire": 0, "hip fire": 0,
    "secondary fire": 1, "ads": 1,
}


def _slot_rank(entry: KitEntry) -> int:
    for token in (entry["mode"], entry["input_key"]):
        rank = SLOT_RANK.get((token or "").strip().lower())
        if rank is not None:
            return rank
    return 2


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


def _stats(fields: Mapping[str, str]) -> dict[str, StatValue]:
    """Every measuring column a row fills, by stat code."""
    stats: dict[str, StatValue] = {}
    for key, raw in fields.items():
        if key in NON_STAT_FIELDS or not raw:
            continue
        value = markup.html_to_text(raw)
        if value:
            stats[STAT_ALIASES.get(key, key)] = StatValue(value, raw)
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


def parse_rows(rows: Iterable[Mapping[str, str]]) -> dict[str, HeroKit]:
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

        base_type, mode = markup.split_type(
            markup.html_to_text(fields.get("ability_type"))
        )
        if not base_type:
            continue

        base = _entry(fields, name, mode)
        kit = heroes.setdefault(hero_name, HeroKit([], [], []))
        lowered = base_type.lower()
        if "perk" in lowered:
            kit.perks.append(PerkEntry(**base, tier="major" if "major" in lowered else "minor"))
        elif lowered.startswith("weapon"):
            kit.weapons.append(WeaponEntry(**base, kind=KIND_WEAPON, display_name=name,
                                           weapon_type=_weapon_type(fields)))
        else:
            kit.abilities.append(AbilityEntry(**base, kind=ability_kind(base_type),
                                              display_name=name))

    for kit in heroes.values():
        kit.weapons.sort(key=_slot_rank)
    return heroes
