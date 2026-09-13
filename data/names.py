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
    ability_key   an ability name across Blizzard and the wiki, which
                  disambiguate differently: "Void Accelerator (Omnic Form)"
                  against "Void Accelerator", "Eject! (D.Mon)" against
                  "Eject!". Drops one trailing parenthetical and folds case;
                  always scoped to one hero, so the looser key cannot
                  collide across heroes.
"""

import re
import unicodedata

NOT_ALNUM_RE = re.compile(r"[^a-z0-9]+")
TRAILING_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")


def name_key(name):
    """Key for recognising the same hero or map across sources."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return NOT_ALNUM_RE.sub("", stripped.lower())


def index(name_to_id):
    """Rekey a {name: id} lookup by name_key."""
    return {name_key(name): value for name, value in name_to_id.items()}


def ability_key(name):
    """Key for recognising the same ability across both sources."""
    return TRAILING_PARENTHETICAL_RE.sub("", name).strip().lower()


def abilities_named_in(description, ability_names):
    """Ability names this text names, longest first so overlaps resolve.

    Matching is scoped to one hero's kit, so a bare name cannot collide with a
    different hero's ability.
    """
    found = []
    for name in sorted(ability_names, key=len, reverse=True):
        if re.search(r"\b%s\b" % re.escape(name), description):
            # Skip a name already covered by a longer one just matched.
            if not any(name in seen for seen in found):
                found.append(name)
    return found
