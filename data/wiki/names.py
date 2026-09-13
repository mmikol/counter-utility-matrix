"""Matching ability names: across the two sources, and inside a description.

Blizzard and the wiki disambiguate differently. Blizzard writes "Void
Accelerator (Omnic Form)" where the wiki writes "Void Accelerator"; the wiki
writes "Eject! (D.Mon)" where Blizzard writes "Eject!". Matching on the raw
name leaves those unclassified and duplicated.
"""

import re

TRAILING_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")


def match_key(name):
    """Key for recognising the same ability across both sources.

    Drops one trailing parenthetical and folds case. Matching is always scoped
    to a single hero, so the looser key cannot collide across heroes.
    """
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
