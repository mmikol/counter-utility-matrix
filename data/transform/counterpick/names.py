"""Matching counterpick.gg's hero and map names against the ones we loaded.

The roster and map pool carry names as Blizzard and the wiki write them -
"Lucio", "D.Va", "Soldier: 76", "King's Row". A third site writes the same
names its own way, and the differences are all punctuation and accents:
"Lucio" against "Lucio", "DVa" against "D.Va", "soldier-76" against
"Soldier: 76".

Lowercasing alone does not close that gap, and a name that fails to match is
not a loud failure - it is a row silently dropped, which is the worst kind. So
matching folds the name down to its letters and digits and compares those.

Scoped to heroes and maps, where the fold cannot collide: no two heroes differ
only by punctuation.
"""

import re
import unicodedata

NOT_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def match_key(name):
    """Key for recognising the same hero or map across sources.

    Decomposes accented characters and drops the combining marks rather than
    folding them to a space - stripping the accent from "Lucio" that way
    yields "Lu io", which matches nothing.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return NOT_ALNUM_RE.sub("", stripped.lower())


def index(name_to_id):
    """Rekey a {name: id} lookup by match_key."""
    return {match_key(name): value for name, value in name_to_id.items()}
