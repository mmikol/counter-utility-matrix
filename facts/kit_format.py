"""The kit in the format in force: the wiki's 6v6 figures laid over the 5v5
rows the kit tables hold, before derive_scalars reads them.

    kit_format.apply(world, KIT_FORMAT)

The load reads each hero's 6v6 pools (heroes.health_6v6, shield_6v6,
armor_6v6) and 6v6 lines (kit_6v6) onto the hero whatever the format, so
the facts can say what 6v6 changes. Under SIX_V_SIX a pool the wiki gives
replaces the 5v5 one, and a line that moves a stat from A to B moves each
row of that stat on the piece it names whose value is A and whose words
hold A once: "100 base + 100 per enemy" holds 100 twice, and a line about
the per-enemy part must not move the base. A line whose A no stat row holds
- the 5v5 figure has moved since the wiki wrote it, or the piece keeps no
such row - is left unapplied and said so, and so is a line with no figure.
Every change is kept on the hero as a KitChange for the facts to word.
"""

import re

from db.data.names import ability_key
from facts.draft import SIX_V_SIX
from facts.kit import KitPiece, Stat
from facts.model import Hero, World
from facts.records import KitChange, KitLine

POOLS = ("health", "shield", "armor")
FIGURE_RE = re.compile(r"\d+(?:\.\d+)?")
# how near a stored value must sit to a line's from figure to be it
SAME = 0.01


def apply(w: World, kit_format: str) -> None:
    """Set the World's format and, under SIX_V_SIX, lay each hero's 6v6
    figures over its kit, recording what moved and what did not."""
    w.kit_format = kit_format
    if kit_format != SIX_V_SIX:
        return
    for hero in w.heroes.values():
        hero.kit_changes = [*_pools(hero), *(_line(hero, line) for line in hero.six_lines)]


def _pools(hero: Hero) -> list[KitChange]:
    """The hero's 6v6 pools in place of its 5v5 ones."""
    changes = []
    for pool in POOLS:
        if pool in hero.six_pools:
            before, after = getattr(hero, pool), hero.six_pools[pool]
            setattr(hero, pool, after)
            changes.append(KitChange(piece="", stat=pool, before=float(before),
                                     after=float(after), applied=True,
                                     text="%s %d in 6v6" % (pool, after)))
    return changes


def _pieces(hero: Hero, name: str) -> list[KitPiece]:
    """The pieces a line names: an ability, a weapon's firing configs, a perk."""
    key = ability_key(name)
    return [k for k in (*hero.abilities, *hero.weapons, *hero.perks)
            if key in (ability_key(k.name), ability_key(k.extra.get("weapon", "")))]


def _holds_once(stat: Stat, figure: float) -> bool:
    """A row whose value is `figure` and whose words hold it once."""
    if stat.value is None or abs(stat.value - figure) > SAME:
        return False
    said = [float(x) for x in FIGURE_RE.findall(stat.text or "")]
    return not said or sum(1 for x in said if abs(x - figure) <= SAME) == 1


def _line(hero: Hero, line: KitLine) -> KitChange:
    """One line laid over the piece it names: every row it moves, or none."""
    moved = False
    if line.stat is not None and line.before is not None and line.after is not None:
        for piece in _pieces(hero, line.piece):
            for stat in piece.stats.get(line.stat, ()):
                if _holds_once(stat, line.before):
                    stat.value = line.after
                    moved = True
    return KitChange(piece=line.piece, stat=line.stat, before=line.before, after=line.after,
                     applied=moved, text=line.text)
