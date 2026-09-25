"""The roster: every hero and map the board tools accept, as the board's
/api/roster and the door's roster tool both list them.
"""

from typing import TypedDict

from facts.draft import is_sided
from facts.model import World


class RosterHero(TypedDict):
    """A hero as the roster lists it: its role and subrole, its health pool,
    its portrait and its status - released, or announced with the release
    day the wiki gives."""
    name: str
    role: str
    subrole: str
    pool: int
    portrait: str | None
    status: str
    release_date: str | None


class RosterMap(TypedDict):
    """A map as the roster lists it: its mode, the style it rewards most
    (Map.style_top) and whether it has an attacking and a defending side."""
    name: str
    mode: str | None
    style: str | None
    sided: bool


class Roster(TypedDict):
    """Every hero, in role order, and every map, in name order."""
    heroes: list[RosterHero]
    maps: list[RosterMap]


def roster_of(world: World) -> Roster:
    """The World's roster: the heroes as world.heroes_by_role() orders them,
    the maps as world.maps_sorted() does."""
    heroes = [
        RosterHero(name=h.name, role=h.role, subrole=h.subrole, pool=h.pool,
                   portrait=h.portrait, status=h.status,
                   release_date=str(h.release_date) if h.release_date else None)
        for h in world.heroes_by_role()]
    maps = [RosterMap(name=m.name, mode=m.mode, style=m.style_top, sided=is_sided(m))
            for m in world.maps_sorted()]
    return Roster(heroes=heroes, maps=maps)
