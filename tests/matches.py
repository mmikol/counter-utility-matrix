"""Recorded matches on the synthetic World, for the validation's tests.

Each map is a 2-2-2 six a side drawn from a string seed, on one of the three
synthetic maps (Harbor Gate from either side), eight maps a session, and
blue's result drawn from a log-odds the test plants. rescored() builds each
map's rescored row without the engine: the team and matchup metrics are the
real ones, and each seat's playbook score is drawn, so a test plants an
effect on the heroes or on the score difference and fits hundreds of maps in
about a second. The engine's own rescore is tested on a handful of maps.
"""

import datetime
import random

from facts.compute import matchup_metrics
from facts.matches import Match
from facts.team import numbers, team_metrics
from inference import fit, rescore, validate

DIGEST = "d" * 64
OTHER_DIGEST = "e" * 64
MAPS = (("Harbor Gate", ("attack", "defense")), ("Ember Ruins", ("",)), ("Salt Flats", ("",)))
PER_SESSION = 8
FIRST_DAY = datetime.date(2026, 1, 1)


def roster(world):
    """The released heroes by role, by name."""
    return {role: sorted(h.name for h in world.heroes.values() if h.released and h.role == role)
            for role in ("tank", "damage", "support")}


def six(rng, by_role):
    """A 2-2-2 six drawn from the roster."""
    return tuple(rng.sample(by_role["tank"], 2) + rng.sample(by_role["damage"], 2)
                 + rng.sample(by_role["support"], 2))


def rescored(world, match, blue_score=0.0, red_score=0.0, blue_terms=None, red_terms=None):
    """A map's rescored row with the given scores: the metrics are the real ones."""
    m, red_h, blue_h, _ = world.resolve(match.map_name, match.red, match.blue, match.bans)
    blue_team = team_metrics(world, blue_h, m, red_h, lean=True)
    red_team = team_metrics(world, red_h, m, blue_h, lean=True)
    return rescore.Rescored(
        match=match, blue_score=blue_score, red_score=red_score,
        blue_terms=blue_terms or {}, red_terms=red_terms or {},
        blue_team=numbers(blue_team), red_team=numbers(red_team),
        matchup=numbers(matchup_metrics(world, blue_team, red_team)))


def rows(world, count, plant, *, seed, digest=DIGEST, per_session=PER_SESSION):
    """`count` rescored maps, oldest first, `per_session` a session: blue won
    each with the chance sigmoid(plant(blue, red, blue's score minus red's)),
    each seat's score drawn from a standard normal."""
    rng = random.Random("matches|%s" % seed)
    by_role = roster(world)
    out = []
    for i in range(count):
        day = FIRST_DAY + datetime.timedelta(days=i // per_session)
        map_name, sides = rng.choice(MAPS)
        side = rng.choice(sides)
        blue, red = six(rng, by_role), six(rng, by_role)
        blue_score, red_score = rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0)
        won = rng.random() < fit.sigmoid(plant(blue, red, blue_score - red_score))
        match = Match(
            match_id=i + 1, played_on=day, map_name=map_name, side=side,
            result=validate.WIN if won else validate.LOSS, blue=blue, red=red, bans=(),
            playbook_digest=digest, note="")
        out.append(rescored(world, match, blue_score, red_score))
    return out


def judged(rows, catalog=(), digest=DIGEST, *, pinned=True, set_aside=0):
    """What assess() is told about the rows: every one recorded under `digest`."""
    matches = [r.match for r in rows]
    return validate.Judged(
        subject=validate.Subject(list(catalog), "tests/fixtures/playbook", digest),
        pins=rescore.pins(matches, digest), recorded=len(matches) + set_aside,
        set_aside=set_aside, pinned=pinned)


def noise(blue, red, diff):
    return 0.0


def anvil(blue, red, diff):
    """Anvil on blue is worth 1.5 log-odds to blue, on red as much to red."""
    return 1.5 * (("Anvil" in blue) - ("Anvil" in red))


def score(blue, red, diff):
    """A standard deviation of the score difference is worth one log-odds."""
    return diff / 2 ** 0.5
