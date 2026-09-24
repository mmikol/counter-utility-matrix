"""The metrics: pure functions over a World.

Every number the board shows as a joint fact and every number a strategy
can reference is computed here or in facts.team, once - the facts
engine renders these into sentences and the inference layer's solver
scores candidate compositions with the same functions. The registries
(TEAM_METRICS in team; MATCHUP_METRICS, MAP_METRICS and WORLD_METRICS
here) are the vocabulary a strategy's frontmatter may use: `team.<key>`,
`enemy.<key>` (the other side's team metrics), `matchup.<key>`,
`map.<key>`, `world.<key>`; registry() gathers them all.

Unknowns are numeric, never None: a metric that needs a map reads 0 (or
falls back to the roster-wide figure where that is the honest substitute,
which the description says) and `map.known` tells a strategy which.
"""

from collections import OrderedDict
from collections.abc import Iterable, Sequence
from typing import NamedTuple, TypedDict

from facts.draft import EXPECTED_SHAPE, is_sided
from facts.model import ROLES, TERRAIN_FEATURES, Hero, Map, World
from facts.team import TEAM_METRICS, MetricBag, number, team_metrics

TREND_POINTS = 1.5
TERRAIN_STANDOUT = 0.75   # sd from the ordinary map at which a terrain feature is a fact
STAGE_MENTIONS = 2        # mentions a stage's text must hold of a feature to stand out on it
STAGE_FEATURES = 2        # standout features a stage fact names, largest first

MATCHUP_METRICS = OrderedDict([
    ("pool_diff", "blue effective HP minus red"),
    ("dps_diff", "blue damage floor minus red"),
    ("hps_diff", "blue healing floor minus red"),
    ("burst_vs_heal", "blue's biggest hit minus red's biggest single save"),
    ("heal_vs_burst", "blue's biggest single save minus red's biggest hit"),
    ("chew_time_ours", "seconds of blue's floor damage to chew red's pool (999 if unknown)"),
    ("chew_time_theirs", "seconds of red's floor damage to chew blue's pool"),
    ("tempo_diff", "red median cooldown minus blue's (positive: blue cycles faster)"),
    ("range_diff", "blue median reach minus red's"),
    ("exposure_share", "share of blue answered by red"),
    ("ult_answers", "blue invulnerabilities plus cleanses"),
])

MAP_METRICS = OrderedDict([
    ("known", "1 if a map is set"),
    ("sided", "1 if the mode has an attacking and a defending side (Escort, Hybrid)"),
    ("side", "this seat's side on a sided map: attack, defense, or empty"),
    ("style_top", "the playstyle the map rewards most: the rates' lift plus the terrain's lean"),
    ("style_margin", "top style score minus the runner-up, in sd"),
    ("mode", "the game mode"),
    ("stages", "separate arenas, one played at a time: Control's 3, Flashpoint's 5; else 0"),
    ("phases", "named parts of one route, played in order: Hybrid's 2, an Escort map's"
                " named stretches; else 0"),
    ("bans", "bans already made in this match: a ban rate is a risk only before them"),
])
TERRAIN_WORDS = {
    "chokes": "chokepoints, narrow streets, corridors, tunnels, gates and doorways",
    "interiors": "rooms, caves and other indoor ground",
    "high_ground": "high ground, rooftops, balconies and other vertical ground",
    "flanks": "flank routes and side paths",
    "sightlines": "long sightlines",
    "open_ground": "open ground and ground said to lack cover",
    "hazards": "drops, pits and other environmental hazards",
    "cover": "cover",
}
# map.<feature>: one per terrain feature, numeric
MAP_METRICS.update((f, "%s: the wiki article's mentions per thousand words, in sd from the mean of"
                       " the maps with text (0 with no text)" % TERRAIN_WORDS[f])
                   for f in TERRAIN_FEATURES)

WORLD_METRICS = OrderedDict([
    ("heal_bench", "2 x the median peak heal across the released supports"),
    ("hps_bench", "2 x the median sustained healing across the released supports"),
    ("roster_size", "heroes in the roster"),
])

SYNERGY_PULL = 2.0        # pick-rate points a hero gains per synergy partner already on the six


class ExpectedPick(TypedDict):
    """One of the other side's likely six: the hero, its role, the pick rate
    it rests on (None for a revealed pick or a hero with no rate), whether it
    was revealed, and the reason in words."""
    hero: str
    role: str
    rate: float | None
    locked: bool
    why: str


def expected_picks(world: World, m: Map | None, *, revealed: Sequence[Hero] = (),
                   banned: Sequence[Hero] = ()) -> list[ExpectedPick]:
    """What the other side is likely to field, from the data alone - no
    strategy read: any picks given as revealed first, then slot by slot the
    hero the map's pick rates (the overall meta with no map set) and the
    wiki's synergies make likeliest - a hero's likelihood is its pick rate
    plus SYNERGY_PULL per partner already on the six - into a two-two-two,
    past the bans. Ties go to the alphabetically first name. Deterministic;
    the board calls it with nothing revealed, so the six is static for the
    board. Each entry says what it rests on."""
    shape = dict(EXPECTED_SHAPE)
    chosen = list(revealed)
    for h in revealed:
        shape[h.role] = max(0, shape.get(h.role, 0) - 1)
    taken = {h.id for h in revealed} | {h.id for h in banned}

    def rate(h: Hero) -> tuple[float | None, bool]:
        r = h.map_pick(m.id) if m is not None else None
        return (r if r is not None else h.pick, r is not None)

    def partners(h: Hero) -> list[Hero]:
        return [c for c in chosen if world.synergy(c.id, h.id)]

    picked: list[ExpectedPick] = []
    while any(shape.values()):
        field = [h for h in world.heroes.values()
                 if h.released and h.id not in taken and shape.get(h.role, 0) > 0]
        if not field:
            break
        best = min(field, key=lambda h: (
            -((rate(h)[0] or 0.0) + SYNERGY_PULL * len(partners(h))), h.name))
        value, on_map = rate(best)
        picked.append({"hero": best.name, "role": best.role, "rate": value, "locked": False,
                       "why": _pick_reason(value, on_map, m, partners(best))})
        chosen.append(best)
        taken.add(best.id)
        shape[best.role] -= 1
    out: list[ExpectedPick] = [
        {"hero": h.name, "role": h.role, "rate": None, "locked": True, "why": "revealed"}
        for h in revealed]
    return out + sorted(picked, key=lambda p: (ROLES.index(p["role"]), p["hero"]))


def _pick_reason(value: float | None, on_map: bool, m: Map | None,
                 partners: Sequence[Hero]) -> str:
    """What an expected pick rests on: its pick rate here, or overall with
    why, and the partners already on the six it pairs with."""
    if value is None:
        why = "no pick rate on record"
    elif on_map and m is not None:
        why = "picked in %.1f%% of matches on %s" % (value, m.name)
    else:
        why = "picked in %.1f%% of matches overall%s" % (
            value, " (no rate on this map)" if m is not None else " (no map set)")
    if partners:
        why += "; pairs with " + ", ".join(c.name for c in partners)
    return why


def matchup_metrics(blue_t: MetricBag, red_t: MetricBag) -> MetricBag:
    """MATCHUP_METRICS from blue's seat, given both teams' metrics.

    Only what reading both sides produces. A number that is already a team
    metric, blue's or red's, is not restated here under a second name: two
    strategies reading the same number through two keys weigh one signal
    twice, and the catalog cannot see that they do. Read team.* for blue's
    own and enemy.* for red's.
    """
    blue_pool, red_pool = number(blue_t["pool_total"]), number(red_t["pool_total"])
    blue_dps, red_dps = number(blue_t["dps_floor"]), number(red_t["dps_floor"])
    blue_heal, red_heal = number(blue_t["heal_peak_max"]), number(red_t["heal_peak_max"])
    blue_burst, red_burst = number(blue_t["burst_max"]), number(red_t["burst_max"])
    size = number(blue_t["size"])
    matchup: MetricBag = {}
    matchup["pool_diff"] = blue_pool - red_pool
    matchup["dps_diff"] = blue_dps - red_dps
    matchup["hps_diff"] = number(blue_t["hps_floor"]) - number(red_t["hps_floor"])
    matchup["burst_vs_heal"] = blue_burst - red_heal
    matchup["heal_vs_burst"] = blue_heal - red_burst
    matchup["chew_time_ours"] = red_pool / blue_dps if blue_dps and red_pool else 999.0
    matchup["chew_time_theirs"] = blue_pool / red_dps if red_dps and blue_pool else 999.0
    matchup["tempo_diff"] = number(red_t["cooldown_median"]) - number(blue_t["cooldown_median"])
    matchup["range_diff"] = number(blue_t["range_median"]) - number(red_t["range_median"])
    matchup["exposure_share"] = number(blue_t["exposed_count"]) / size if size else 0.0
    matchup["ult_answers"] = number(blue_t["invuln"]) + number(blue_t["cleanse"])
    return matchup


def arenas(m: Map | None) -> list[str]:
    """The map's stages where each is its own ground (Control, Flashpoint)."""
    return [] if m is None or is_sided(m) else list(m.stages)


def phases(m: Map | None) -> list[str]:
    """The map's stages where they are parts of one route (Hybrid, Escort)."""
    return list(m.stages) if m is not None and is_sided(m) else []


class Standout(NamedTuple):
    """A terrain feature a stage's own text stresses, and its z there."""
    feature: str
    z: float


def stage_standouts(m: Map, stage: str) -> list[Standout]:
    """The features a stage's own text stresses: z at or over TERRAIN_STANDOUT
    on STAGE_MENTIONS or more mentions, largest first, STAGE_FEATURES at most.
    Stage texts are short: one mention swings the rate, and none says nothing."""
    terrain, z = m.stage_terrain.get(stage, {}), m.stage_z.get(stage, {})
    found = [Standout(f, z[f]) for f in TERRAIN_FEATURES
            if f in terrain and z.get(f, 0.0) >= TERRAIN_STANDOUT
            and terrain[f].mentions >= STAGE_MENTIONS]
    return sorted(found, key=lambda s: (-s.z, s.feature))[:STAGE_FEATURES]


def map_metrics(m: Map | None, side: str = "", *, ban_count: int) -> MetricBag:
    if m is None:
        return {"known": 0, "sided": 0, "side": "", "style_top": "",
                "style_margin": 0, "mode": "", "stages": 0, "phases": 0, "bans": ban_count,
                **dict.fromkeys(TERRAIN_FEATURES, 0.0)}
    sided = 1 if is_sided(m) else 0
    return {"known": 1, "sided": sided, "side": side if sided else "",
            "style_top": m.style_top or "", "style_margin": m.style_margin,
            "mode": m.mode or "", "stages": len(arenas(m)),
            "phases": len(phases(m)), "bans": ban_count,
            **{f: m.terrain_z[f] for f in TERRAIN_FEATURES}}


def world_metrics(world: World) -> MetricBag:
    return {"heal_bench": world.heal_bench, "hps_bench": world.hps_bench,
            "roster_size": len(world.heroes)}


def namespace(
        world: World, m: Map | None, red: Iterable[Hero], blue: Iterable[Hero],
        side: str = "", *, ban_count: int) -> dict[str, MetricBag]:
    """The whole evaluation namespace for a board: {team, enemy, matchup,
    map, world} - `team` is blue's seat, `enemy` is red's, `side` blue's."""
    blue_t = team_metrics(world, blue, m, red)
    red_t = team_metrics(world, red, m, blue)
    return {"team": blue_t, "enemy": red_t,
            "matchup": matchup_metrics(blue_t, red_t),
            "map": map_metrics(m, side, ban_count=ban_count), "world": world_metrics(world)}


# Metrics whose value is a name or a list, not a number: a heuristic may not
# maximize them, but a constraint may compare them ("team.style_lean == 'dive'").
TEXT_METRICS = {
    "team.subroles", "team.shape_flags", "team.style_counts", "team.style_top",
    "team.style_lean", "team.weakest", "team.squishies", "team.burst_hero",
    "team.isolated", "team.pairs", "team.max_ban_hero", "team.unanswered", "team.exposed",
    "map.style_top", "map.mode", "map.side",
}
TEXT_METRICS |= {n.replace("team.", "enemy.", 1) for n in TEXT_METRICS if n.startswith("team.")}

# team metrics that read the other side. The solver builds red's metrics once,
# facing no one, so as enemy.* these would all read zero: not offered
VERSUS_KEYS = frozenset((
    "coverage", "coverage_share", "unanswered", "answer_edges", "exposure_edges",
    "exposed_count", "exposed", "safe_count", "net_edges", "double_covered",
    "banproof_coverage"))


def registry() -> dict[str, str]:
    """Every dotted key a strategy may reference -> its description."""
    out: dict[str, str] = {}
    for prefix, table in (("team", TEAM_METRICS), ("enemy", TEAM_METRICS),
                          ("matchup", MATCHUP_METRICS), ("map", MAP_METRICS),
                          ("world", WORLD_METRICS)):
        for key, description in table.items():
            if prefix == "enemy" and key in VERSUS_KEYS:
                continue
            out["%s.%s" % (prefix, key)] = description
    return out
