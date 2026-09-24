"""The board's vocabulary: a lobby's limits and the refusal of a team past
them, the sides of a sided map, and the Draft - the board at one stage of
the pick-and-ban draft - with the pair of functions both HTTP doors read
and write one with. A leaf: it imports only the model and db's Refusal, so
every other module in the package can take these names from it.
"""

from collections.abc import Iterable, Mapping, Sequence, Sized
from typing import NamedTuple

from db import Refusal
from ui.facts.model import Hero, Map

TEAM_SIZE = 6             # 6v6 Open Queue
MAX_TANKS = 2             # the queue's own limit, whatever the playbook holds
MAX_BANS = 5              # each team's two and the lobby's
SIDED_MODES = ("Escort", "Hybrid")   # modes with an attacking and a defending side
SIDES = ("attack", "defense")
EXPECTED_SHAPE = {"tank": 2, "damage": 2, "support": 2}   # what a lobby fields: two of each


def check_team_size(picks: Sized, seat: str) -> None:
    """Refuse a team of more picks than a lobby seats."""
    if len(picks) > TEAM_SIZE:
        raise Refusal("more than %d %s picks" % (TEAM_SIZE, seat))


def check_tanks(heroes: Iterable[Hero], seat: str) -> None:
    """Refuse a team the queue would not seat: more than MAX_TANKS tanks. The
    limit is the game's, so it binds whatever the playbook holds."""
    tanks = sum(1 for h in heroes if h.role == "tank")
    if tanks > MAX_TANKS:
        raise Refusal("the queue allows at most %d tanks, and %s picks %d"
                      % (MAX_TANKS, seat, tanks))


class Draft(NamedTuple):
    """The board at one stage of the pick-and-ban draft."""
    map_name: str | None = None
    red: tuple[str, ...] = ()
    blue: tuple[str, ...] = ()
    bans: tuple[str, ...] = ()
    side: str = ""


# --- the board as query parameters ---------------------------------------------
#
# Both doors - ui/board.py and inference/serve.py - name a board the same way on
# the wire, and the two halves live here, beside the limits they enforce, so
# neither door owns the other's spelling. A Draft holds tuples: a list in a field
# makes an equal-looking Draft compare unequal.

def parse_board(query: Mapping[str, Sequence[str]]) -> Draft:
    """The board a parsed query names, its bans cut to MAX_BANS. A team of
    more than TEAM_SIZE picks is refused, not cut: no lobby seats it, and a
    cut would answer a board the caller did not send."""
    maps, sides = query.get("map"), query.get("side")
    red = tuple(x for x in query.get("red", ()) if x)
    blue = tuple(x for x in query.get("blue", ()) if x)
    check_team_size(red, "red")
    check_team_size(blue, "blue")
    return Draft(map_name=(maps[0] or None) if maps else None, red=red, blue=blue,
                 bans=tuple(x for x in query.get("bans", ()) if x)[:MAX_BANS],
                 side=sides[0] if sides else "")


def board_query(draft: Draft) -> dict[str, str | list[str]]:
    """A board as query parameters, in the spelling parse_board reads back."""
    return {"map": draft.map_name or "", "side": draft.side, "red": list(draft.red),
            "blue": list(draft.blue), "bans": list(draft.bans)}


def is_sided(m: Map | None) -> bool:
    """Whether the map has an attacking and a defending side."""
    return m is not None and (m.mode or "") in SIDED_MODES


def opposite(side: str) -> str:
    """The other seat's side; no side stays none."""
    return {"attack": "defense", "defense": "attack"}.get(side, "")
