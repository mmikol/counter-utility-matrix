"""Reach: every hero is the right pick somewhere.

The playbook may make a hero rare; it may not make one impossible. For a hero this finds
a board that suits it - one of its maps, a red it answers, a side - on which it is in the
optimal six, banning the rivals that hold its seat where it must, up to the five bans a
match has. A hero with no such board is one the facts or the strategies cannot
see: a wrong number, a tool no metric reads, a rule that charges it for what it is not.

    maps   the four its map rates lift it most on (its three best maps are among them)
    reds   none (blue counters the likely six); the heroes it answers, two a role, the
           most exposed to it first; the same without the heroes that answer it back
"""

from inference import engine
from ui.facts import compute

MAPS = 4
MAX_BANS = compute.MAX_BANS       # a match bans up to five; a rival banned is a real board
CLOSEST = 5                       # boards the ban search starts from


def maps(world, hero):
    base = hero.win or 50.0

    def lift(m):
        return (hero.map_win(m.id) or base) - base

    return sorted(world.maps.values(), key=lambda m: (-lift(m), m.name))[:MAPS]


def reds(world, hero):
    others = [h for h in world.heroes.values() if h.released and h.id != hero.id]
    out = [[]]
    for strict in (False, True):
        red = []
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


def search(world, name):
    """-> {"hero", "bans": 0..MAX_BANS or None, "map", "side", "red", "banned", "six",
    "gap"}: the first board that seats the hero; with none, the closest it came."""
    hero = world.hero(name)
    near = []
    for m in maps(world, hero):
        for red in reds(world, hero):
            for side in (compute.SIDES if compute.is_sided(m) else ("",)):
                top = engine.infer(world, m.name, red, [], side=side, top=1)
                if hero.name in top.blue:
                    return {"hero": hero.name, "bans": 0, "map": m.name, "side": side,
                            "red": red, "banned": [], "six": top.blue, "gap": 0.0}
                held = engine.infer(world, m.name, red, [hero.name], side=side, top=1)
                near.append((top.score - held.score, m.name, red, side))
    near.sort(key=lambda t: (t[0], t[1], t[3]))
    for _, map_name, red, side in near[:CLOSEST]:
        banned = []
        for _ in range(MAX_BANS):
            top = engine.infer(world, map_name, red, [], side=side, bans=banned, top=1)
            held = engine.infer(world, map_name, red, [hero.name], side=side, bans=banned,
                                top=1)
            rivals = [h for h in top.blue if world.hero(h).role == hero.role
                      and h not in held.blue and h not in red]
            if not rivals:
                break
            banned = [*banned, rivals[0]]
            top = engine.infer(world, map_name, red, [], side=side, bans=banned, top=1)
            if hero.name in top.blue:
                return {"hero": hero.name, "bans": len(banned), "map": map_name, "side": side,
                        "red": red, "banned": banned, "six": top.blue, "gap": 0.0}
    gap, map_name, red, side = near[0]
    return {"hero": hero.name, "bans": None, "map": map_name, "side": side, "red": red,
            "banned": [], "six": [], "gap": round(gap, 3)}


def seated(world, board):
    """Is the hero still in the optimal six of the board a search recorded for it?"""
    top = engine.infer(world, board["map"], board["red"], [], side=board["side"],
                       bans=board["banned"], top=1)
    return board["hero"] in top.blue
