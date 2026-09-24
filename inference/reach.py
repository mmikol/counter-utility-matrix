"""Reach: is a hero the right pick somewhere?

The intent is that the playbook makes a hero rare but never impossible. This is the
check, not the guarantee: for a hero it looks for a board that suits it - one of its
maps, a red it answers, a side - on which it is in the optimal six, banning the rivals
that hold its seat where it must, up to the five bans a match has.

The two answers it gives are not symmetric. A board found is a proof: the hero seats
there, and re-solving that board shows it. A board not found is not a proof of the
opposite - the search tries a few maps and a few reds, and a board it never visits could
seat the hero. A hero it finds nothing for is one worth looking at: a wrong number, a
tool no metric reads, a rule that charges it for what it is not, or a board this search
does not reach. Fifty-one of the fifty-three released heroes have a board; Freja and
Shion do not, as of the scale that stopped moving with the bans.

    maps   the four its map rates lift it most on (its three best maps are among them)
    reds   none (blue counters the likely six); the heroes it answers, two a role, the
           most exposed to it first; the same without the heroes that answer it back
"""

from typing import TypedDict

from inference import engine
from ui.facts.draft import MAX_BANS, SIDES, Draft, is_sided
from ui.facts.model import Hero, Map, World

MAPS = 4
CLOSEST = 5         # boards the ban search starts from


class Reach(TypedDict):
    """A board a search found for a hero - the reach tool's answer and a row of
    tests/fixtures/reach.json. bans counts the rivals banned (banned names them);
    None means no board seated the hero, and the rest is the closest it came,
    gap the score it fell short by."""
    hero: str
    bans: int | None
    map: str
    side: str
    red: list[str]
    banned: list[str]
    six: list[str]
    gap: float


def maps(world: World, hero: Hero) -> list[Map]:
    base = hero.win or 50.0

    def lift(m: Map) -> float:
        return (hero.map_win(m.id) or base) - base

    return sorted(world.maps.values(), key=lambda m: (-lift(m), m.name))[:MAPS]


def reds(world: World, hero: Hero) -> list[list[str]]:
    others = [h for h in world.heroes.values() if h.released and h.id != hero.id]
    out: list[list[str]] = [[]]
    for strict in (False, True):
        red: list[str] = []
        for role in ("tank", "damage", "support"):
            pool = [h for h in others if h.role == role
                    and not (strict and world.counters_of(hero.id, h.id))]
            pool.sort(key=lambda h: (-bool(world.counters_of(h.id, hero.id)),
                                     bool(world.counters_of(hero.id, h.id)),
                                     -(h.pick or 0), h.name))
            red += [h.name for h in pool[:2]]
        if red not in out:
            out.append(red)
    return out


def _role(world: World, name: str) -> str | None:
    """The role of a hero the engine named, which the World always holds."""
    found = world.hero(name)
    return found.role if found else None


def search(world: World, name: str) -> Reach:
    """The first board that seats the hero, bans 0..MAX_BANS; with none, bans
    None and the closest it came. An unknown or announced hero is the Refusal
    World.resolve gives every board tool; a database without maps leaves no
    board to search, which is the server's fault, a RuntimeError."""
    (hero,) = world.resolve(None, (), [name]).blue
    near: list[tuple[float, str, list[str], str]] = []
    for m in maps(world, hero):
        for red in reds(world, hero):
            for side in (SIDES if is_sided(m) else ("",)):
                top = engine.infer(world, Draft(m.name, tuple(red), side=side), top=1)
                if hero.name in top.blue:
                    return {"hero": hero.name, "bans": 0, "map": m.name, "side": side,
                            "red": red, "banned": [], "six": top.blue, "gap": 0.0}
                held = engine.infer(world, Draft(m.name, tuple(red), (hero.name,), side=side),
                                    top=1)
                near.append((top.score - held.score, m.name, red, side))
    if not near:
        raise RuntimeError("reach: no board to search for %s: the database holds no maps"
                           % hero.name)
    near.sort(key=lambda t: (t[0], t[1], t[3]))
    for _, map_name, red, side in near[:CLOSEST]:
        found = _banning(world, hero, map_name, red, side)
        if found is not None:
            return found
    gap, map_name, red, side = near[0]
    return {"hero": hero.name, "bans": None, "map": map_name, "side": side, "red": red,
            "banned": [], "six": [], "gap": round(gap, 3)}


def _banning(world: World, hero: Hero, map_name: str, red: list[str], side: str) -> Reach | None:
    """One board's ban search: each round bans the first rival that holds the
    hero's seat, up to MAX_BANS -> the board once the hero seats, or None when
    it never does or no rival is left to ban."""
    banned: list[str] = []
    # one solve of this board per ban, not two: the board a ban produces is
    # the board the next round starts from, so the round reads it
    for _ in range(MAX_BANS + 1):
        top = engine.infer(world, Draft(map_name, tuple(red), (), tuple(banned), side), top=1)
        if banned and hero.name in top.blue:
            return {"hero": hero.name, "bans": len(banned), "map": map_name, "side": side,
                    "red": red, "banned": banned, "six": top.blue, "gap": 0.0}
        if len(banned) == MAX_BANS:
            break
        held = engine.infer(world, Draft(map_name, tuple(red), (hero.name,), tuple(banned), side),
                            top=1)
        rivals = [h for h in top.blue if _role(world, h) == hero.role
                  and h not in held.blue and h not in red]
        if not rivals:
            break
        banned = [*banned, rivals[0]]
    return None


def seated(world: World, board: Reach) -> bool:
    """Is the hero still in the optimal six of the board a search recorded for it?"""
    top = engine.infer(world, Draft(board["map"], tuple(board["red"]), (), tuple(board["banned"]),
                                    board["side"]), top=1)
    return board["hero"] in top.blue
