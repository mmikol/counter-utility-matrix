"""The board in prose: the momentum verdict read off the two current comps,
and the game plan - the ground, what to play on it, what red's picks mean,
the family of heroes to stay in and what the six is built for - worded from
the facts and strategies the solver scored.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import NamedTuple

from inference.result import Momentum, Odds, Result
from ui.facts.draft import TEAM_SIZE
from ui.facts.factset import FactSet
from ui.facts.model import Hero, Map, World
from ui.facts.team import team_metrics, text


class Seats(NamedTuple):
    """What the verdict reads off a board: the two current comps; the two
    optimals, whose reason a seat with no picks is read by; the two fills,
    the best six reachable from a half-drafted seat's picks, which that seat
    is read through; and blue's picks against red's best counter."""
    current: Result
    red_current: Result
    blue: Result | None = None
    red: Result | None = None
    fill: Result | None = None
    red_fill: Result | None = None
    countered: Result | None = None


def momentum(seats: Seats) -> Momentum:
    """Who the picks favour, read off the two current comps on their own
    optimals' scales: blue's share of its best counter to red's selection,
    red's share of its best counter to blue's. A seat with no picks has no
    contributions to name a waiting strategy by, so its reason is read off
    its optimal instead.

    A half-drafted seat is read through its fill - the best six reachable from
    what it has - on both sides alike. Scoring the picks alone sums over a
    smaller team, so a perfectly played draft would read low and could fall
    when the right pick lands; that measures how many picks are in, not how
    good they are, and a seat read that way against one read through its
    fill would always trail."""
    cur, red_cur = seats.current, seats.red_current
    blue_why = cur.unscored() if cur.blue or seats.blue is None else seats.blue.waiting()
    red_why = red_cur.unscored() if red_cur.blue or seats.red is None else seats.red.waiting()
    if blue_why and red_why:                       # neither seat can be a share of anything
        return Momentum(blue=None, red=None, countered=None, partial=False, odds=None,
                        verdict=blue_why)
    n, m, k = _shares(seats, blue_why, red_why)
    odds = _odds(n, m)
    partial = bool((cur.blue and cur.partial) or (red_cur.blue and red_cur.partial))
    verdict = _verdict_line(cur, red_cur, n, m, partial, odds, blue_why, red_why)
    if k is not None:
        verdict += "; if red plays its best counter, your picks hold %d / 100" % k
    return Momentum(blue=n, red=m, countered=k, partial=partial, odds=odds, verdict=verdict)


def _shares(
        seats: Seats, blue_why: str | None,
        red_why: str | None) -> tuple[int | None, int | None, int | None]:
    """Blue's share of its optimal, red's of its best counter, and blue's
    against red's best counter; None where a seat has no picks or its share
    waits. Each half-drafted seat is read through its fill where one was
    solved, and the countered case is a fill of blue's picks too, so the
    three are measured the same way."""
    cur, red_cur, countered = seats.current, seats.red_current, seats.countered
    n = _now(cur, seats.fill).share() if cur.blue and not blue_why else None
    m = _now(red_cur, seats.red_fill).share() if red_cur.blue and not red_why else None
    k = None
    if countered is not None and countered.blue and not countered.unscored():
        k = countered.share()
    return n, m, k


def _now(current: Result, fill: Result | None) -> Result:
    """A seat as the verdict reads it: its fill while it is half-drafted and
    one was solved, else its current comp."""
    return fill if fill is not None and current.partial and current.blue else current


def _odds(n: int | None, m: int | None) -> Odds | None:
    """The fight odds: the two shares pitted against each other - each side's
    share of the two shares' sum, so the pair reads as a split of 100; defined
    only when both seats score."""
    if n is None or m is None or n + m <= 0:
        return None
    blue = round(100.0 * n / (n + m))
    return Odds(blue=blue, red=100 - blue)


def _verdict_line(cur: Result, red_cur: Result, n: int | None, m: int | None, partial: bool,
                  odds: Odds | None, blue_why: str | None, red_why: str | None) -> str:
    """The verdict in words, before the countered hedge."""
    if (blue_why and cur.blue) or (red_why and red_cur.blue):   # one seat scores, the other waits
        return _one_seat_waits(cur, red_cur, n, m, blue_why, red_why)
    if n is not None and m is not None:
        return _gap_line(n, m, partial, odds)
    if m is not None:
        return "red has revealed picks and blue has none: red %d / 100 of its best counter" % m
    if n is not None:
        return "no red picks revealed yet: blue %d / 100 of its optimal" % n
    return "no picks yet on either side"


def _one_seat_waits(cur: Result, red_cur: Result, n: int | None, m: int | None,
                    blue_why: str | None, red_why: str | None) -> str:
    """Each seat on its own: a seat with picks has its share, unless its
    reason for none waits."""
    def waits(why: str | None) -> str:
        return "unscored: " + (why or "").split(": ", 1)[-1]
    sides = [
        "no blue picks yet" if not cur.blue else
        "blue %d / 100 of its optimal" % n if n is not None else
        "blue " + waits(blue_why),
        "no red picks revealed yet" if not red_cur.blue else
        "red %d / 100 of its best counter" % m if m is not None else
        "red " + waits(red_why)]
    return "; ".join(sides)


def _gap_line(n: int, m: int, partial: bool, odds: Odds | None) -> str:
    """Both seats scored: who is ahead and by how much, and the fight odds."""
    gap = n - m
    if abs(gap) < 5:
        line = "even - blue %d, red %d" % (n, m)
    elif gap > 0:
        line = "blue ahead by %d - blue %d, red %d" % (gap, n, m)
    else:
        line = "red ahead by %d - blue %d, red %d" % (-gap, n, m)
    if partial:
        line += " (partial picks)"
    if odds:
        line += "; fight odds blue %d%%, red %d%%" % (odds["blue"], odds["red"])
    return line


MODE_GROUND = {
    "Control": "one point in three arenas - whoever holds the point's ground holds the round",
    "Escort": "a payload path with a choke between phases - the fight moves with the cart",
    "Hybrid":
        "a capture point and then the payload path - the first fight is at the point,"
        " the rest along the route",
    "Push": "one long lane with the robot - fights follow the barricade and regrouping"
            " costs distance",
    "Flashpoint": "five points across a wide map - long rotations between fast fights, so"
                  " arriving first and together matters",
}
STYLE_PLAY = {
    "dive": "pick a target, commit together with mobile tanks and flankers, and get out with"
            " supports who can follow",
    "brawl":
        "hold ground as a group, sustain the front line with area healing, and win the"
        " close-range trade",
    "poke": "take the long sightlines, chip from range with healers who reach, and make them"
            " walk into damage",
}
SAME_LEAN = {
    "dive": "both sides dive - peel for your backline first, then commit on theirs",
    "brawl":
        "both sides fight at close range - the side that sustains longer and trades"
        " ultimates better wins the ground",
    "poke": "both sides chip from range - take the sightlines first and win the range trade",
}
THEIR_LEAN = {
    "dive": "expect them to commit on one of your backline - stay together, peel, and punish"
            " the divers as they land",
    "brawl":
        "they want to hold ground as a group - do not walk into their front line; split"
        " them or out-range them",
    "poke": "they want to chip from range - close the distance behind cover or take the"
            " sightlines first",
}
SIDE_PLAY = {
    "attack":
        "attacking: you have to break their hold, so take the high ground before you"
        " commit and go in together",
    "defense":
        "defending: the ground is yours - set up on the high ground and make them"
        " walk into you",
}


# the map.terrain facts' features, as the plan words them
TERRAIN_GROUND = {
    "chokes": "chokes", "interiors": "interiors", "high_ground": "high ground",
    "flanks": "flank routes", "sightlines": "long sightlines", "open_ground": "open ground",
    "hazards": "environmental hazards", "cover": "cover",
}

TERRAIN_NAMED = 3   # standout features the plan names, largest first
STAGES_NAMED = 3    # stages the plan names for their terrain, largest first, in play order


def _and(items: Iterable[str]) -> str:
    items = list(items)
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".")
    return text[:1].upper() + text[1:] + "."


FAMILY_SIZE = 5     # heroes the plan names per role


def _family(world: World, m: Map | None, style: str, role: str,
            bans: Iterable[str]) -> list[str]:
    """A style's heroes in one role, by the wiki's playstyle tags: released
    and unbanned, fewest tags first, then best win rate here."""
    out = {h.name for h in map(world.hero, bans) if h is not None}

    def rate(h: Hero) -> float:
        return (h.map_win(m.id) if m is not None else None) or h.win or 0.0
    heroes = [
        h for h in world.heroes.values()
        if h.role == role and style in h.styles and h.released and h.name not in out]
    return [h.name for h in sorted(heroes, key=lambda h: (len(h.styles), -rate(h), h.name))
            ][:FAMILY_SIZE]


def plan(
        world: World, m: Map | None, side: str, bans: Sequence[str],
        red_h: Sequence[Hero], blue_r: Result) -> str:
    """The game plan in prose - the ground, what to play on it, what red's
    picks mean (their likely six until one is revealed), the family of heroes
    to stay in when you stray from the six, and what the six is built for -
    from the same facts and strategies the solver scored, so that picks can be
    tailored toward the optimal without matching it. Ends with what it rests on."""
    lean = blue_r.playstyle
    read = _ground(m, side, blue_r.facts)
    style = _style_read(m, lean, red_h)
    if style is not None:
        read.append(style)
    lines = [" ".join(read)]
    for line in (_them(world, m, red_h, lean, blue_r), _family_line(world, m, lean, bans),
                 _above_all(blue_r, lean)):
        if line is not None:
            lines.append(line)
    lines.append(_basis(m, side, bans, red_h))
    return "\n".join(lines)


def _ground(m: Map | None, side: str, facts: FactSet | None) -> list[str]:
    """The ground: the map's mode, the terrain its facts stress, and the side."""
    if m is None:
        return ["No map yet, so this is the meta's best six: what is winning right now, built"
                " to fit together."]
    ground = MODE_GROUND.get(m.mode or "", "the fight follows the objective")
    read = ["%s is a %s map: %s." % (m.name, m.mode, ground)]
    if facts is not None:
        read += _terrain(m, facts)
    if side in SIDE_PLAY:
        read.append("You are " + SIDE_PLAY[side] + ".")
    return read


def _terrain(m: Map, facts: FactSet) -> list[str]:
    """The ground the wiki's article stresses - the map.terrain facts above
    the ordinary map - and the stages whose own text stresses a feature, the
    map.stage_terrain facts."""
    read = []
    stressed = [f.value["feature"] for f in facts.find("map.terrain", m.name)
                if f.value["z"] > 0][:TERRAIN_NAMED]
    if stressed:
        read.append("The wiki's article stresses %s."
                    % _and(TERRAIN_GROUND[f] for f in stressed))
    stressing = sorted(facts.find("map.stage_terrain", m.name),
                       key=lambda f: -f.value["features"][0]["z"])[:STAGES_NAMED]
    staged = [
        (f.value["stage"], _and(TERRAIN_GROUND[x["feature"]] for x in f.value["features"]))
        for f in sorted(stressing, key=lambda f: m.stages.index(f.value["stage"]))]
    if staged:
        read.append("; ".join(("%s has the %s" if i == 0 else "%s the %s") % pair
                              for i, pair in enumerate(staged)) + ".")
    return read


def _style_read(m: Map | None, lean: str, red_h: Sequence[Hero]) -> str | None:
    """What to play: the style the map rewards against the six's lean."""
    map_style = m.style_top if m is not None else ""
    if map_style and lean == map_style:
        return "The map rewards %s and the six leans into it: %s." % (lean, STYLE_PLAY[lean])
    if map_style and lean:
        return ("The map rewards %s, but %sthe six leans %s: %s."
                % (map_style, "against this red " if red_h else "", lean,
                   STYLE_PLAY.get(lean, "play to its picks")))
    if lean:
        return "The six leans %s: %s." % (lean, STYLE_PLAY.get(lean, "play to its picks"))
    if map_style:
        return "The map rewards %s: %s." % (map_style, STYLE_PLAY[map_style])
    return None


def _them(
        world: World, m: Map | None, red_h: Sequence[Hero], lean: str,
        blue_r: Result) -> str | None:
    """What red's picks mean: their lean against the six's, and which picks
    of the six answer which of theirs - read off the hero.vs_answers facts
    the picks cite. With nothing revealed, the likely six the six counters."""
    if not red_h:
        if blue_r.red:
            return ("No red pick yet: the six counters their likely six (%s)."
                    % ", ".join(blue_r.red))
        return None
    n = len(red_h)
    theirs = team_metrics(world, red_h, m, [])
    red_lean = text(theirs["style_lean"]) or text(theirs["style_top"])
    them = "Their %d pick%s%s (%s)" % (n, "" if n == 1 else "s",
                                        " so far" if n < TEAM_SIZE else "",
                                        ", ".join(h.name for h in red_h))
    s = "s" if n == 1 else ""
    if red_lean in THEIR_LEAN and red_lean == lean:
        them += " lean%s %s too: %s." % (s, red_lean, SAME_LEAN[red_lean])
    elif red_lean in THEIR_LEAN:
        them += " lean%s %s: %s." % (s, red_lean, THEIR_LEAN[red_lean])
    else:
        them += " show%s no lean yet." % s
    return them + _answers([h.name for h in red_h], _answered(blue_r))


def _answered(six: Result) -> dict[str, list[str]]:
    """Each enemy the six answers, and the picks of the six that answer it,
    in pick order: the hero.vs_answers facts filed under the six's own side,
    the facts its picks' reasons cite."""
    answered: dict[str, list[str]] = {}
    if six.facts is None:
        return answered
    for p in six.picks:
        for f in six.facts.find("hero.vs_answers", p["hero"]):
            if f.team == "blue":
                for enemy in f.value:
                    answered.setdefault(enemy, []).append(p["hero"])
    return answered


def _answers(names: Sequence[str], answered: Mapping[str, Sequence[str]]) -> str:
    """Who in the six answers each of red's picks, most answered first, and
    the picks nobody answers."""
    out = ""
    pairs = sorted(((k, v) for k, v in answered.items() if k in names),
                   key=lambda kv: -len(kv[1]))
    if pairs:
        out += " " + _sentence("; ".join(
            "%s answer%s %s" % (_and(v), "" if len(v) > 1 else "s", k) for k, v in pairs[:4]))
    missing = [k for k in names if k not in answered]
    if missing:
        out += " Nobody in the six answers %s - respect %s." % (
            _and(missing), "them" if len(missing) > 1 else "that pick")
    return out


def _family_line(world: World, m: Map | None, lean: str, bans: Sequence[str]) -> str | None:
    """The family to stay in: the six's style's heroes in each role."""
    if not lean:
        return None
    parts = []
    for role, plural in (("tank", "Tanks"), ("damage", "Damage"), ("support", "Supports")):
        names = _family(world, m, lean, role, bans)
        if names:
            parts.append("%s: %s." % (plural, ", ".join(names)))
    if not parts:
        return None
    return "If you stray from the six, stay in its family. " + " ".join(parts)


def _above_all(blue_r: Result, lean: str) -> str | None:
    """What the six is built for: its four heaviest scoring terms - not the
    shape every legal six pays, nor a rule named for another style ("Dive the
    pocket" on a poke six); a rule on the map's style is about the map."""
    titles = {h.id: h.name for h in blue_r.catalog}
    skip = {h.id for h in blue_r.catalog
            if (h.kind == "constraint" and h.category == "shape")
            or (h.name.split()[0].lower() in STYLE_PLAY and h.name.split()[0].lower() != lean
                and not (h.when and "map.style_top" in h.when.names))}
    top = sorted((c for c in blue_r.contributions
                  if c["applies"] and c["weighted"] > 0.05
                  and c["id"] not in skip),
                 key=lambda c: -c["weighted"])[:4]
    if not top:
        return None
    return ("Above all: "
            + "; ".join(titles.get(str(c["id"]), str(c["id"])).lower() for c in top) + ".")


def _basis(m: Map | None, side: str, bans: Sequence[str], red_h: Sequence[Hero]) -> str:
    """What the plan rests on."""
    basis = ["the rates and counters"]
    if m is not None:
        basis.append("the map")
    if side:
        basis.append("the side")
    if bans:
        basis.append("%d ban%s" % (len(bans), "" if len(bans) == 1 else "s"))
    if red_h:
        basis.append("red's %d revealed pick%s" % (len(red_h), "" if len(red_h) == 1 else "s"))
    return "Based on: %s." % ", ".join(basis)
