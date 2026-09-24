"""Groups the wiki's weapon entries into weapons and their firing configs.

The wiki lists one entry per firing mode, so Ana's rifle appears twice -
"Biotic Rifle" (Hip Fire) and "Zoom (ADS)". Those are one weapon. But Mauga's
"Incendiary Chaingun" and "Volatile Chaingun" are two weapons he fires
independently, and the wiki types both exactly the same way.

Three signals separate them, applied in order:

1.  A shared base name after dropping an "Alt Fire" or "(ADS)" suffix
    ("Particle Cannon" / "Particle Cannon Alt Fire") is one weapon.
2.  A Hip Fire entry followed by an ADS entry is one weapon, whatever the ADS
    entry is called ("Biotic Rifle" then "Zoom (ADS)").
3.  A Primary Fire entry followed by a Secondary Fire entry is one weapon
    UNLESS both names end in the same noun. Two weapons of one class get named
    "<modifier> <noun>" twice - Incendiary Chaingun, Volatile Chaingun - while
    a fire mode is named for what it does (Peacekeeper, Fan the Hammer).

Form-based entries (Mech/Pilot, Recon/Assault, Omnic/Nemesis) never merge:
those are different loadouts, not modes of one gun.
"""

import re
from typing import NamedTuple

from db.data.wiki.kit_rows import WeaponEntry

ALT_SUFFIX_RE = re.compile(r"\s*(?:alt(?:ernate)?\s*fire|\(ads\))\s*$", re.I)
WORD_RE = re.compile(r"[A-Za-z']+")

# The wiki's firing modes -> weapon_config_slots.slot_id (seeded in 002_heroes.sql).
SLOT_IDS = {
    "": 1,
    "primary fire": 2,
    "secondary fire": 3,
    "hip fire": 4,
    "ads": 5,
}
DEFAULT_SLOT = SLOT_IDS[""]
ADS_SLOT = SLOT_IDS["ads"]

MERGEABLE_SEQUENCES = {("hip fire", "ads"), ("primary fire", "secondary fire")}


def base_name(name: str) -> str:
    """A weapon's name without its "Alt Fire" or "(ADS)" suffix."""
    return ALT_SUFFIX_RE.sub("", name).strip()


def head_noun(name: str) -> str:
    """The last word of the base name, lowercased: "chaingun"."""
    words = WORD_RE.findall(base_name(name))
    return words[-1].lower() if words else ""


def slot_id(mode: str | None) -> int:
    """A firing mode's weapon_config_slots.slot_id; an unknown mode is the default."""
    return SLOT_IDS.get((mode or "").strip().lower(), DEFAULT_SLOT)


def _merges(previous: WeaponEntry, entry: WeaponEntry) -> bool:
    previous_mode = (previous["mode"] or "").strip().lower()
    entry_mode = (entry["mode"] or "").strip().lower()

    if base_name(previous["name"]).lower() == base_name(entry["name"]).lower():
        return True
    if (previous_mode, entry_mode) not in MERGEABLE_SEQUENCES:
        return False
    if (previous_mode, entry_mode) == ("primary fire", "secondary fire"):
        # Same head noun means two weapons of one class, not one weapon.
        return head_noun(previous["name"]) != head_noun(entry["name"])
    return True


class Weapon(NamedTuple):
    """A weapon and its firing configs, in source order."""
    name: str
    configs: list[WeaponEntry]


def group_weapons(entries: list[WeaponEntry]) -> list[Weapon]:
    """[weapon entry] -> [Weapon(name, [config entry])] in source order.

    Also names each ADS config after the weapon it belongs to. The wiki calls
    them anything - "Zoom (ADS)", "Take Aim (ADS)" - and the weapon's own name
    is only known once the configs are grouped, which is why it happens here.
    """
    weapons: list[Weapon] = []
    for entry in entries:
        if weapons and _merges(weapons[-1].configs[-1], entry):
            weapons[-1].configs.append(entry)
        else:
            weapons.append(Weapon(base_name(entry["name"]), [entry]))

    for weapon in weapons:
        for config in weapon.configs:
            if slot_id(config["mode"] or config["input_key"]) == ADS_SLOT:
                config["display_name"] = "%s (ADS)" % weapon.name
    return weapons
