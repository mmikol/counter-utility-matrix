"""The board's vocabulary: a lobby's limits and the refusal of a team past
them, the sides of a sided map, and the Draft - the board at one stage of
the pick-and-ban draft, which refuses a board no lobby holds - with
parse_board, the one reader of a board off the wire, shared by the page and
the service because the page's board runs through serve.handle_board. A
playbook draft - a strategy awaiting its frontmatter - is another thing. A
leaf: it imports only the model and db's Refusal, so every other module in
the package can take these names from it.
"""

from collections.abc import Iterable, Mapping, Sequence, Sized
from dataclasses import dataclass

from db import Refusal
from facts.model import Hero, Map

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


@dataclass(frozen=True)
class Draft:
    """The board at one stage of the pick-and-ban draft. It refuses a board
    no lobby holds - a team past TEAM_SIZE picks, bans past MAX_BANS, a side
    that is not one - when it is built, dataclasses.replace included, so
    every door that builds one refuses the same boards."""
    map_name: str | None = None
    red: tuple[str, ...] = ()
    blue: tuple[str, ...] = ()
    bans: tuple[str, ...] = ()
    side: str = ""

    def __post_init__(self) -> None:
        check_team_size(self.red, "red")
        check_team_size(self.blue, "blue")
        if len(self.bans) > MAX_BANS:
            raise Refusal("more than %d bans" % MAX_BANS)
        if self.side not in ("", *SIDES):
            raise Refusal("side must be attack or defense, got %r" % self.side)


# --- the board off the wire -----------------------------------------------------
#
# Both HTTP doors - ui/board.py and inference/serve.py - read a board off a
# query string with parse_board. The limits belong to Draft, so these doors
# and the MCP board tools (door/mcp/boards.py) refuse the same boards. A
# Draft holds tuples: a list in a field makes an equal-looking Draft compare
# unequal.

# A parsed query string, as both doors hand it to parse_board
type Query = Mapping[str, Sequence[str]]


def parse_board(query: Query) -> Draft:
    """The board a parsed query names, its empty values dropped. Draft
    refuses any board no lobby holds, and nothing is cut: a cut would answer
    a board the caller did not send."""
    maps, sides = query.get("map"), query.get("side")
    return Draft(map_name=(maps[0] or None) if maps else None,
                 red=tuple(x for x in query.get("red", ()) if x),
                 blue=tuple(x for x in query.get("blue", ()) if x),
                 bans=tuple(x for x in query.get("bans", ()) if x),
                 side=sides[0] if sides else "")


def is_sided(m: Map | None) -> bool:
    """Whether the map has an attacking and a defending side."""
    return m is not None and (m.mode or "") in SIDED_MODES


def opposite(side: str) -> str:
    """The other seat's side; no side stays none."""
    return {"attack": "defense", "defense": "attack"}.get(side, "")
