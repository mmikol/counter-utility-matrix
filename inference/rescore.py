"""The recorded maps a playbook is judged on, and what the engine says about
each: the pin, the rescore from both seats, and the playbook's scoring
strategies in the families an ablation drops.

    families    the playbook's scoring strategies in the groups an ablation
                drops together - side bonuses, counters, synergy, the rates,
                the other scored constraints, the rest - each named by the
                ids it holds
    pins        the digests the matches were played under; a playbook is
                judged only on the maps from the first one played under it,
                so it is never judged on the maps it was tuned on
    rescore     each map through engine.evaluate from both seats - blue's six
                against red's on blue's side, red's against blue's on the
                other - with the team and matchup metrics of both sixes
    without     a map's playbook score difference with some strategies'
                terms dropped
"""

from collections.abc import Callable, Iterable, Sequence
from typing import NamedTuple, TypedDict

from db import Log, Refusal
from facts.compute import matchup_metrics
from facts.draft import Draft, opposite
from facts.matches import Match
from facts.model import World
from facts.team import VERSUS_METRICS, numbers, team_metrics
from inference import engine
from inference.strategy import Strategy

POOL = 2                    # the field evaluate ranks against: a six's score is the
                            # same at any pool, since the scale is drawn at its own
PROGRESS_EVERY = 10         # maps rescored between progress lines


# --- the families ---------------------------------------------------------------

def _keyed(sections: Iterable[str], keys: Iterable[str]) -> frozenset[str]:
    """Every section.key pair, as a strategy names a metric."""
    keys = tuple(keys)
    return frozenset("%s.%s" % (s, k) for s in sections for k in keys)


# the metrics each family is recognised by, as a strategy's metric, confidence
# or expressions name them
SIDE_KEYS = frozenset({"map.side"})
COUNTER_KEYS = _keyed(("team",), VERSUS_METRICS) | {"matchup.exposure_share"}
SYNERGY_KEYS = _keyed(("team", "enemy"), (
    "synergy_edges", "synergy_score", "synergy_density", "isolated_count", "isolated",
    "core_size", "pairs"))
# Blizzard's rates: the meta and map sections of the team metrics, and the map's
# style, which the per-map rates lift
RATE_KEYS = _keyed(("team", "enemy"), (
    "win_mean", "pick_mass", "availability", "map_availability", "max_ban_rate",
    "max_ban_hero", "rank_sensitive_count", "trend_sum", "map_win_mean", "map_pick_mass",
    "map_specialists", "map_offmap", "home_map_hits", "style_fit")) | {
    "map.style_top", "map.style_margin"}


class Family(NamedTuple):
    """Strategies an ablation drops together: the family's name, what it
    is, and the ids of the playbook's strategies in it."""
    name: str
    meaning: str
    ids: tuple[str, ...]


def _names(strategy: Strategy) -> set[str]:
    """Every metric a strategy reads: its metric, its confidence, and the
    names its expressions read."""
    names = {n for n in (strategy.metric, strategy.confidence) if n}
    for expr in (strategy.when, strategy.require, strategy.bonus, strategy.penalty):
        if expr is not None:
            names |= set(expr.names)
    return names


def scores(strategy: Strategy) -> bool:
    """Whether a strategy moves a six's score: a heuristic, a scored
    constraint or a soft limit. A hard limit prunes and adds nothing."""
    return strategy.form in ("heuristic", "scored") or (
        strategy.form == "limit" and strategy.soft)


# the families in the order a strategy is filed: the first whose test it meets
FAMILY_TESTS: tuple[tuple[str, str, Callable[[Strategy], bool]], ...] = (
    ("side", "the side bonuses: rules that read map.side",
        lambda s: bool(_names(s) & SIDE_KEYS)),
    ("counters", "the counter family: rules on the counters table's edges",
        lambda s: bool(_names(s) & COUNTER_KEYS)),
    ("synergy", "cohesion: rules on the wiki's synergy pairs",
        lambda s: bool(_names(s) & SYNERGY_KEYS)),
    ("rates", "the rate-reading rules: Blizzard's win, pick and ban rates",
        lambda s: bool(_names(s) & RATE_KEYS)),
    ("scored", "the other scored constraints", lambda s: s.form == "scored"),
    ("other", "the rest that scores: kit heuristics and soft limits", lambda s: True),
)


def families(catalog: Sequence[Strategy]) -> list[Family]:
    """The playbook's scoring strategies, each in the first family whose
    test it meets; a family the playbook holds nothing of is left out."""
    filed: dict[str, list[str]] = {}
    for strategy in catalog:
        if not scores(strategy):
            continue
        name = next(name for name, _meaning, test in FAMILY_TESTS if test(strategy))
        filed.setdefault(name, []).append(strategy.id)
    return [Family(name, meaning, tuple(sorted(filed[name])))
            for name, meaning, _test in FAMILY_TESTS if name in filed]


# --- the pin --------------------------------------------------------------------

class Pin(TypedDict):
    """One digest the recorded maps were played under: how many, the first
    and last date, and whether it is the playbook this run judges."""
    digest: str
    maps: int
    first: str
    last: str
    judged: bool


def pins(matches: Sequence[Match], digest: str) -> list[Pin]:
    """Each digest the matches were played under, in the order it first
    appears; the matches are oldest first."""
    table: dict[str, Pin] = {}
    for match in matches:
        day = match.played_on.isoformat()
        pin = table.setdefault(match.playbook_digest, Pin(
            digest=match.playbook_digest, maps=0, first=day, last=day,
            judged=match.playbook_digest == digest))
        pin["maps"] += 1
        pin["last"] = day
    return list(table.values())


def pinned(matches: Sequence[Match], digest: str) -> list[Match]:
    """The maps a playbook may be judged on: from the first one played under
    its digest on, whatever digest the later ones carry. A map before it may
    be one the playbook was tuned on; none, where no map carries it."""
    for i, match in enumerate(matches):
        if match.playbook_digest == digest:
            return list(matches[i:])
    return []


# --- the rescore ----------------------------------------------------------------

class Rescored(NamedTuple):
    """One recorded map through the engine: each seat's playbook score from
    evaluate on its own seat's scale, each seat's term per strategy id, both
    sixes' numeric team metrics (each against the other) and the matchup
    metrics from blue's seat."""
    match: Match
    blue_score: float
    red_score: float
    blue_terms: dict[str, float]
    red_terms: dict[str, float]
    blue_team: dict[str, float]
    red_team: dict[str, float]
    matchup: dict[str, float]


class Refused(NamedTuple):
    """A recorded map the engine would not score, and why."""
    match_id: int
    reason: str


class Rescoring(NamedTuple):
    """What the rescore made of the maps: the scored ones and the refused."""
    scored: list[Rescored]
    refused: list[Refused]


def seats(match: Match) -> tuple[Draft, Draft]:
    """The map from each seat: blue's six against red's on blue's side, and
    red's against blue's on the other side."""
    return (Draft(map_name=match.map_name, red=match.red, blue=match.blue, bans=match.bans,
                  side=match.side),
            Draft(map_name=match.map_name, red=match.blue, blue=match.red, bans=match.bans,
                  side=opposite(match.side)))


def rescored(
        world: World, match: Match, catalog: list[Strategy],
        pool_size: int = POOL) -> Rescored:
    """One map rescored: engine.evaluate from both seats, then the team and
    matchup metrics. A board the engine refuses raises its Refusal."""
    blue_seat, red_seat = seats(match)
    blue = engine.evaluate(world, blue_seat, catalog=catalog, pool_size=pool_size)
    red = engine.evaluate(world, red_seat, catalog=catalog, pool_size=pool_size)
    m, red_h, blue_h, _bans = world.resolve(match.map_name, match.red, match.blue, match.bans)
    blue_team = team_metrics(world, blue_h, m, red_h, lean=True)
    red_team = team_metrics(world, red_h, m, blue_h, lean=True)
    return Rescored(
        match=match, blue_score=blue.score, red_score=red.score,
        blue_terms={c["id"]: c["weighted"] for c in blue.contributions},
        red_terms={c["id"]: c["weighted"] for c in red.contributions},
        blue_team=numbers(blue_team), red_team=numbers(red_team),
        matchup=numbers(matchup_metrics(blue_team, red_team)))


def rescore(world: World, matches: Sequence[Match], catalog: list[Strategy], *,
            pool_size: int = POOL, log: Log | None = None) -> Rescoring:
    """Every map rescored, in order; a map the engine refuses - a hero the
    database no longer holds, a board no six satisfies - is listed with the
    reason instead. A progress line every PROGRESS_EVERY maps goes to `log`."""
    done, refused = [], []
    for i, match in enumerate(matches, 1):
        try:
            done.append(rescored(world, match, catalog, pool_size))
        except Refusal as error:
            refused.append(Refused(match.match_id, str(error)))
        if log is not None and (i % PROGRESS_EVERY == 0 or i == len(matches)):
            log("validate: %d of %d maps rescored" % (i, len(matches)))
    return Rescoring(done, refused)


def without(row: Rescored, ids: Iterable[str]) -> float:
    """Blue's score minus red's, less every term of the strategies named:
    the playbook score difference with a family dropped. The scale each
    heuristic is normalised on stays the full playbook's."""
    dropped = set(ids)
    blue = row.blue_score - sum(v for k, v in row.blue_terms.items() if k in dropped)
    red = row.red_score - sum(v for k, v in row.red_terms.items() if k in dropped)
    return blue - red
