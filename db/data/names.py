"""Matching names across sources: two keys, for two different problems.

    name_key      a hero or map name across sites. The roster and map pool
                  carry names as Blizzard and the wiki write them - "Lúcio",
                  "D.Va", "Soldier: 76", "King's Row" - and a third site
                  writes them its own way: "Lucio", "DVa", "soldier-76".
                  The differences are all punctuation and accents, and a
                  name that fails to match is not a loud failure but a row
                  silently dropped, so the key folds a name down to its
                  letters and digits (accents decomposed and stripped, not
                  turned into spaces: "Lu io" would match nothing). Scoped
                  to heroes and maps, where no two differ only by punctuation.
    hero_key      name_key through RENAMED, for a source that may still
                  write a hero's former name
    RENAMED       {former name_key: current name_key}
    ability_key   an ability name across Blizzard and the wiki, which
                  disambiguate differently: "Void Accelerator (Omnic Form)"
                  against "Void Accelerator", "Eject! (D.Mon)" against
                  "Eject!". Drops one trailing parenthetical and folds case;
                  always scoped to one hero, so the looser key cannot
                  collide across heroes.

    index               a {name: id} lookup rekeyed by name_key
    unaccented          a name with its accents dropped: "Lúcio" -> "Lucio"
    slug                a hero's slug as Blizzard's links write it:
                        "Soldier: 76" -> soldier-76, "D.Va" -> dva
"""

import re
import unicodedata
from collections.abc import Mapping

NOT_ALNUM_RE = re.compile(r"[^a-z0-9]+")
NOT_ALNUM_OR_SPACE_RE = re.compile(r"[^a-z0-9\s]+")
TRAILING_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")
# A hero the wiki's older rows still link under a former name. The former
# name is also what matchups reads the hero by in the wiki's prose.
RENAMED = {"mccree": "cassidy"}


def unaccented(name: str) -> str:
    """The name with its accents dropped (NFKD, combining marks removed)."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def name_key(name: str) -> str:
    """Key for recognising the same hero or map across sources."""
    return NOT_ALNUM_RE.sub("", unaccented(name).lower())


def hero_key(name: str) -> str:
    """name_key, with a former hero name keyed as the current one."""
    key = name_key(name)
    return RENAMED.get(key, key)


def slug(name: str) -> str:
    """A hero's slug as Blizzard's links write it: the name unaccented and
    lowercased, its punctuation deleted, its words joined by hyphens."""
    return "-".join(NOT_ALNUM_OR_SPACE_RE.sub("", unaccented(name).lower()).split())


def index(name_to_id: Mapping[str, int]) -> dict[str, int]:
    """Rekey a {name: id} lookup by name_key."""
    return {name_key(name): value for name, value in name_to_id.items()}


def ability_key(name: str) -> str:
    """Key for recognising the same ability across both sources."""
    return TRAILING_PARENTHETICAL_RE.sub("", name).strip().lower()
