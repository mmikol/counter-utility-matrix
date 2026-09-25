"""The default engine: what a six scores before the playbook adds a term.

    base(six) = W_RATE x rates + W_SYNERGY x synergy + W_COUNTER x counters

    rates       each pick's win rate on the map, all ranks (its overall rate
                where there is no map or no row for it), in points over 50,
                times the share of that edge its pick rate earns - p / (p +
                RATE_PICK_HALF), the map's pick rate on a map - and averaged
                over the six
    synergy     team.synergy_score: the wiki's synergy scores among the six
    counters    the wiki's counter edges between the six and the other side:
                the picks that answer it less the picks it answers back. The
                other side is its locked picks; with none, its likely six on
                this map (compute.expected_picks, past the bans), which only
                this term reads

It is always on and needs no playbook: under a playbook of assumptions the
board's sixes are the ones these three favour, and the strategies' terms
sit on top of it (inference.scoring). A heuristic moves a six by its weight
at most, since its norm is in [0, 1].

The rate term is centred on 50, a coin flip, and not on the reference
sample's mean: the zero is the same on every board, so a six's term needs no
sample and is a function of the six and the board alone; the pull toward 50
for a rarely picked hero shrinks to that same zero; and a comp's share of
the optimal reads as its share of the optimal's edge over a coin flip.

The weights. W_RATE is 1: the rate term is in win-rate points. The other two
are set so that each term's median range within one board is about half the
rate term's, measured over the reference sample (inference.scale.sample,
1,200 legal sixes a board) on each of the 30 maps of the database's capture
of September 2026, each board's other side its likely six, the side the
term reads until one is revealed. The rate term's median range was 4.8
points (map_win_mean's, unpulled, 6.6), the synergy score's 21 and the net
counter edges' 17.5; with two red picks revealed the counter edges' was 12.
Half the rate term's range is 0.114 of the synergy score's and 0.137 of the
counter edges', rounded to 0.1 and 0.15: at the median a board's sixes
spread about 4.8 points on rates, 2.1 on synergy and 2.6 on counters. These
are defaults, which recorded match outcomes will refit. OFF zeroes all
three, and a board scored under it is the playbook's alone, exactly as
before the engine had a base.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple, TypedDict

from facts import compute
from facts.factset import Fact, FactSet
from facts.model import Hero, Map, World

W_RATE = 1.0            # points of score per point of trusted win-rate edge
W_SYNERGY = 0.1         # per point of the wiki's synergy scores among the six
W_COUNTER = 0.15        # per net counter edge against the other side
COIN_FLIP = 50.0        # the win rate the rate term is centred on
# The pick rate at which a hero's edge is trusted by half: trust = p / (p +
# RATE_PICK_HALF). A rarely picked hero's rate is read off few matches and
# swings, so its edge is pulled toward 50. Set to the tenth percentile of the
# released heroes' pick rates, all ranks and per map alike, at the capture of
# September 2026, rounded to a whole point: only the rarest tenth lose more
# than half their edge, and a hero picked at the median keeps about three
# quarters of it.
RATE_PICK_HALF = 3.0

# the three terms' ids in a six's breakdown: a strategy's id is lowercase
# kebab, so none can take a dotted one
RATES, SYNERGY, COUNTERS = "base.rates", "base.synergy", "base.counters"
# what each term reads, as the breakdown words it, and its name in the game plan
READS = {
    RATES: "the six's win rates on the map, each trusted by its pick rate",
    SYNERGY: "team.synergy_score, the wiki's synergy scores among the six",
    COUNTERS: "the wiki's counter edges between the six and the other side"}
TITLES = {
    RATES: "Win rates here", SYNERGY: "The wiki's synergy pairs",
    COUNTERS: "Answers to the other side"}


@dataclass(frozen=True, slots=True)
class BaseWeights:
    """The default engine's weights, each term's points per unit. A board,
    the objective and every result carry one, so a board says what it was
    scored under; OFF zeroes all three."""
    rate: float = W_RATE
    synergy: float = W_SYNERGY
    counter: float = W_COUNTER

    @property
    def on(self) -> bool:
        """Whether any term scores."""
        return bool(self.rate or self.synergy or self.counter)


DEFAULT = BaseWeights()
OFF = BaseWeights(rate=0.0, synergy=0.0, counter=0.0)


class BaseStamp(TypedDict):
    """The default engine as a recorded fixture holds it: the weights and the
    pick rate that halves an edge, which with the playbook fix what a six
    scores."""
    rate: float
    synergy: float
    counter: float
    pick_half: float


def stamp(weights: BaseWeights) -> BaseStamp | None:
    """What a fixture recorded under `weights` holds of the engine; None
    with it off, as a fixture recorded before the engine had a base reads."""
    if not weights.on:
        return None
    return BaseStamp(rate=weights.rate, synergy=weights.synergy, counter=weights.counter,
                     pick_half=RATE_PICK_HALF)


class Opponent(NamedTuple):
    """The other side the counter term reads: its heroes, and whether they are
    its likely six rather than picks it has made."""
    heroes: tuple[Hero, ...]
    likely: bool


class Edges(NamedTuple):
    """One hero's counter edges against the other side: the heroes of that
    side it answers, and those that answer it."""
    answers: int
    exposures: int


class Terms(NamedTuple):
    """A six's three base terms, unweighted: the trusted rate edge in points,
    the synergy score, and the counter edges each way."""
    rates: float
    synergy: float
    answers: int
    exposures: int

    @property
    def counters(self) -> int:
        """Answer edges less exposure edges: team.net_edges against the
        other side the term reads."""
        return self.answers - self.exposures


def likely_six(world: World, m: Map | None, banned: Sequence[Hero]) -> tuple[Hero, ...]:
    """A side's likely six on this map past the bans, the one the board's red
    panel shows: compute.expected_picks with nothing revealed."""
    heroes = [world.hero(p["hero"]) for p in compute.expected_picks(world, m, banned=banned)]
    return tuple(h for h in heroes if h is not None)


def opponent(
        world: World, m: Map | None, red: Sequence[Hero], banned: Sequence[Hero]) -> Opponent:
    """The other side as the counter term reads it: its locked picks, else its
    likely six. Handed exactly that likely six, as the board hands blue's
    seat until red reveals a pick, it is the likely six still."""
    likely = likely_six(world, m, banned)
    if not red:
        return Opponent(heroes=likely, likely=True)
    same = {h.id for h in red} == {h.id for h in likely}
    return Opponent(heroes=tuple(red), likely=same)


def rate_edge(h: Hero, m: Map | None) -> float:
    """One hero's trusted win-rate edge in points: its win rate on the map
    (overall where there is no map or no row for it) over COIN_FLIP, times
    p / (p + RATE_PICK_HALF) for its pick rate p on the same footing - the
    map's where the map's row gives one. A hero with no rate has no edge."""
    row = h.map_rates.get(m.id) if m is not None else None
    win, pick = (row.win, row.pick) if row is not None else (h.win, h.pick)
    if pick is None:
        pick = h.pick
    if win is None or not pick:
        return 0.0
    return pick / (pick + RATE_PICK_HALF) * (win - COIN_FLIP)


class Base:
    """The default engine on one board: its weights, the other side the
    counter term reads, and each hero's trusted rate edge on the map and
    counter edges against that side, read once. A six's terms are then a
    sum of lookups and the synergy score its metrics already hold."""

    def __init__(self, world: World, m: Map | None, *, red: Sequence[Hero],
                 banned: Sequence[Hero], weights: BaseWeights) -> None:
        self.weights = weights
        self.opponent = opponent(world, m, red, banned)
        against = self.opponent.heroes
        self._edge = {h.id: rate_edge(h, m) for h in world.heroes.values()}
        self._edges = {h.id: Edges(
            answers=sum(1 for e in against if world.is_countered_by(e.id, h.id)),
            exposures=sum(1 for e in against if world.is_countered_by(h.id, e.id)))
            for h in world.heroes.values()}

    def terms(self, heroes: Sequence[Hero], synergy: float) -> Terms:
        """A six's terms. The edges are summed exactly (math.fsum), so a six
        scores the same in any seat order and in any process."""
        rates = math.fsum(self._edge[h.id] for h in heroes) / len(heroes) if heroes else 0.0
        return Terms(rates=rates, synergy=synergy,
                     answers=sum(self._edges[h.id].answers for h in heroes),
                     exposures=sum(self._edges[h.id].exposures for h in heroes))

    def value(self, terms: Terms) -> float:
        """The weighted sum, in one order everywhere it is taken."""
        w = self.weights
        return w.rate * terms.rates + w.synergy * terms.synergy + w.counter * terms.counters


# The facts the two terms no board fact states. A result's FactSet files the
# seat's own six as "blue", whichever seat it is, so the facts are filed there
# too; their words name the sides as the seat sees them.

def write_rates_fact(fs: FactSet, *, seat: str, map_name: str | None, rates: float) -> Fact:
    """The fact the rate term cites: the six's trusted edge over a coin flip."""
    where = "on %s" % map_name if map_name else "across the maps"
    fs.add(
        "team", "blue", RATES,
        "%s's six %s: %+.2f win-rate points over 50 a pick, all ranks, each pick's edge"
        " trusted by its pick rate" % (seat, where, rates),
        value=rates, unit="points", source="derived:" + RATES, team="blue")
    return fs.find(RATES)[-1]


def write_counters_fact(
        fs: FactSet, *, seat: str, map_name: str | None, against: Sequence[str],
        likely: bool, answers: int, exposures: int) -> Fact:
    """The fact the counter term cites: which of the other side's sixes it
    read - its picks, or its likely six - and the edges each way."""
    other = "blue" if seat == "red" else "red"
    if likely:
        whom = "%s's likely six %s" % (other, "on %s" % map_name if map_name else "with no map")
    else:
        whom = "%s as it stands" % other
    fs.add(
        "team", "blue", COUNTERS,
        "counters read %s: %s - %d answer-edges into it, %d back (%+d)"
        % (whom, ", ".join(against), answers, exposures, answers - exposures),
        value=answers - exposures, source="derived:" + COUNTERS, team="blue")
    return fs.find(COUNTERS)[-1]
