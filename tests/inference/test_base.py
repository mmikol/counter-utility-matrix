"""The default engine: each of its three terms worked by hand, the pick
rate's pull toward a coin flip, the other side it reads - the likely six
until that side locks a pick, from either seat - the sliced board against
the one-process board, the facts its terms cite, and a playbook of
assumptions alone scored by it, its best six the enumerated maximum. Every
board is the synthetic World's: no database."""

import copy
import itertools
import os
import shutil
from concurrent.futures import Future

import pytest

from facts import compute, counters
from facts.draft import Draft
from facts.factset import FactSet
from facts.records import DerivedEdge, Fired, MapRate
from inference import base, catalog, engine, scoring
from inference.base import DEFAULT, OFF, W_COUNTER
from tests.inference import ASSUMPTIONS_ONLY, FIXTURE_PLAYBOOK, timeless
from tests.inference.tracing import TRACED

SIX = ("Anvil", "Kite", "Rook", "Needle", "Balm", "Tansy")


def heroes(world, names):
    return [world.hero(n) for n in names]


def prepared(world, map_name, red, six, playbook=ASSUMPTIONS_ONLY, weights=DEFAULT, banned=()):
    """The Objective of a board and a six prepared and scored on it."""
    m = world.map(map_name) if map_name else None
    objective = scoring.Objective(world, m, red=heroes(world, red), catalog=playbook,
                                  base=weights, banned=heroes(world, banned))
    return objective, objective.score(objective.prepare(scoring.Candidate(heroes(world, six))))


def test_the_rate_term_is_each_picks_edge_over_a_coin_flip_trusted_by_its_pick_rate(
        synthetic_world):
    """On Harbor Gate a pick's win and pick rate are the map's; with no map,
    or no row for the hero, its overall ones; a row with no pick rate takes
    the overall pick rate. The term is the mean over the six, in points."""
    w = synthetic_world
    harbor = w.map("Harbor Gate")
    half = base.RATE_PICK_HALF
    # Harbor Gate's rows: Anvil 52.5 on 12, Kite 50 on 8, Rook 53.5 on 7, Needle 50 on 9,
    # Balm 52 on 10, Tansy 49 on 4.5
    edges = [
        12 / (12 + half) * 2.5, 0.0, 7 / (7 + half) * 3.5, 0.0, 10 / (10 + half) * 2.0,
        4.5 / (4.5 + half) * -1.0]
    for name, edge in zip(SIX, edges, strict=True):
        assert base.rate_edge(w.hero(name), harbor) == pytest.approx(edge), name
    _, cand = prepared(w, "Harbor Gate", ("Mortar", "Gale"), SIX)
    assert cand.terms.rates == pytest.approx(sum(edges) / 6)
    # no map: Rook's overall 51.5 on 8
    rook = w.hero("Rook")
    assert base.rate_edge(rook, None) == pytest.approx(8 / (8 + half) * 1.5)
    unrowed = copy.copy(rook)
    unrowed.map_rates = {k: v for k, v in rook.map_rates.items() if k != harbor.id}
    assert base.rate_edge(unrowed, harbor) == base.rate_edge(rook, None)
    unpicked = copy.copy(rook)
    unpicked.map_rates = {**rook.map_rates, harbor.id: MapRate(53.5, None)}
    assert base.rate_edge(unpicked, harbor) == pytest.approx(8 / (8 + half) * 3.5)


def test_a_rarely_picked_heroes_edge_is_pulled_toward_a_coin_flip(synthetic_world):
    """trust = p / (p + RATE_PICK_HALF): half the edge at RATE_PICK_HALF, less
    below it, none at no pick rate, nearly all of it for a staple."""
    rook = copy.copy(synthetic_world.hero("Rook"))
    rook.map_rates = {}
    rook.win = 54.0

    def edge(pick):
        rook.pick = pick
        return base.rate_edge(rook, None)
    half = base.RATE_PICK_HALF
    assert edge(half) == pytest.approx(2.0)
    assert edge(half / 3) == pytest.approx(1.0) and edge(0.0) == 0.0 and edge(None) == 0.0
    assert 3.9 < edge(100 * half) < 4.0
    picks = [0.5, 1.0, half, 2 * half, 10 * half]
    assert [edge(p) for p in picks] == sorted(edge(p) for p in picks)
    rook.win = 46.0
    assert edge(half) == pytest.approx(-2.0)          # a weak hero's deficit is pulled in too


def test_the_synergy_and_counter_terms_read_the_wikis_pairs_and_edges(synthetic_world):
    """Synergy is team.synergy_score (Anvil+Balm 2, Needle+Tansy 2); against
    red's locked picks the counter term is the graph's weight each way, every
    edge here the wiki's at WIKI_WEIGHT: Anvil answers Mortar, Needle answers
    Gale, Gale answers Anvil - two in, one back, twice team.net_edges. Each
    term is its weight times its raw value, and the score their sum."""
    objective, cand = prepared(synthetic_world, "Harbor Gate", ("Mortar", "Gale"), SIX)
    team = cand.ns["team"]
    assert cand.terms.synergy == team["synergy_score"] == 4
    assert (cand.terms.answers, cand.terms.exposures) == (4, 2)
    assert cand.terms.counters == counters.WIKI_WEIGHT * team["net_edges"] == 2
    assert objective.base.opponent == base.Opponent(
        heroes=tuple(heroes(synthetic_world, ("Mortar", "Gale"))), likely=False)
    terms = {c["id"]: c for c in cand.contributions}
    assert list(terms) == [base.RATES, base.SYNERGY, base.COUNTERS]    # nothing else scores
    for key, raw, weight in ((base.RATES, cand.terms.rates, base.W_RATE),
                             (base.SYNERGY, 4, base.W_SYNERGY),
                             (base.COUNTERS, 2, base.W_COUNTER)):
        c = terms[key]
        assert c["kind"] == c["form"] == "base" and c["applies"]
        assert c["raw"] == pytest.approx(raw) and c["weight"] == weight
        assert c["weighted"] == pytest.approx(weight * raw)
    assert cand.score == pytest.approx(sum(c["weighted"] for c in cand.contributions))
    assert terms[base.COUNTERS]["against"] == ["Mortar", "Gale"]


def test_off_adds_nothing_and_the_playbook_scores_alone(synthetic_world):
    """OFF: no base terms, no base breakdown, and a six scores what the
    playbook's terms sum to; the default engine adds exactly its value."""
    fix = catalog.load(FIXTURE_PLAYBOOK)
    off_objective, off = prepared(synthetic_world, "Harbor Gate", ("Mortar", "Gale"), SIX, fix,
                                  OFF)
    assert off_objective.base is None and off.terms is None
    assert not any(c["kind"] == "base" for c in off.contributions)
    on_objective, on = prepared(synthetic_world, "Harbor Gate", ("Mortar", "Gale"), SIX, fix)
    on_objective.adopt_bounds(off_objective.bounds)
    assert on.score - off.score == pytest.approx(on_objective.base.value(on.terms))


def test_the_counters_read_the_likely_six_until_the_other_side_locks_a_pick(synthetic_world):
    """With no red pick the counter term reads red's likely six on the map,
    past the bans - the six the board's red panel shows - and nothing else
    does: team.net_edges and every enemy.* key still read an empty red. One
    locked pick and the term reads that pick alone."""
    w = synthetic_world
    likely = [p["hero"] for p in compute.expected_picks(w, w.map("Harbor Gate"),
                                                        banned=heroes(w, ("Needle",)))]
    assert "Needle" not in likely and len(likely) == 6
    objective, cand = prepared(w, "Harbor Gate", (), SIX, banned=("Needle",))
    assert objective.base.opponent.likely and objective.red == []
    assert [h.name for h in objective.base.opponent.heroes] == likely
    answers = sum(counters.WIKI_WEIGHT for e in likely for h in SIX
                  if w.is_countered_by(w.hero(e).id, w.hero(h).id))
    exposures = sum(counters.WIKI_WEIGHT for h in SIX for e in likely
                    if w.is_countered_by(w.hero(h).id, w.hero(e).id))
    assert (cand.terms.answers, cand.terms.exposures) == (answers, exposures) != (0, 0)
    assert cand.ns["team"]["net_edges"] == 0 and cand.ns["enemy"]["size"] == 0
    assert objective.static["enemy"] == scoring.team_metrics(w, [], w.map("Harbor Gate"), ())
    _, locked = prepared(w, "Harbor Gate", ("Gale",), SIX, banned=("Needle",))
    # Needle answers Gale, Gale answers Anvil: a wiki edge each way
    assert (locked.terms.answers, locked.terms.exposures) == (2, 2)
    [c] = [c for c in locked.contributions if c["id"] == base.COUNTERS]
    assert c["against"] == ["Gale"] and c["likely"] is False
    # handed exactly the likely six as picks, as the board hands blue's seat, it is
    # the likely six still
    objective, _ = prepared(w, "Harbor Gate", likely, SIX[:1], banned=("Needle",))
    assert objective.base.opponent.likely


def test_each_seat_reads_the_other_sides_likely_six_or_its_picks(synthetic_world):
    """The board's two seats alike: before blue picks, red's optimal reads
    blue's likely six as blue's optimal reads red's; once blue locks a pick,
    red's reads that pick. Each counter term cites the fact that says which."""
    empty = engine.board(synthetic_world, Draft("Harbor Gate", side="attack"),
                         catalog=ASSUMPTIONS_ONLY)
    likely = empty.expected.blue
    # the plan says the six counters it, and names the engine's terms it is built on
    assert "No red pick yet: the six counters their likely six (" in empty.plan
    assert "the highest win-rate six" not in empty.plan
    assert "Above all: win rates here" in empty.plan
    for seat, other in ((empty.blue, "red"), (empty.red, "blue")):
        [c] = [c for c in seat.contributions if c["id"] == base.COUNTERS]
        assert sorted(c["against"]) == sorted(likely) and c["likely"], seat.seat
        assert c["text"] == "counters read %s's likely six on Harbor Gate: %s - %d into it, %d" \
            " back (%+d), a wiki edge 2 and a derived one 1" % (
                other, ", ".join(c["against"]), c["answers"], c["exposures"],
                c["answers"] - c["exposures"])
    held = engine.board(synthetic_world, Draft("Harbor Gate", (), ("Balm",), side="attack"),
                        catalog=ASSUMPTIONS_ONLY)
    [c] = [c for c in held.red.contributions if c["id"] == base.COUNTERS]
    assert c["against"] == ["Balm"] and not c["likely"]
    assert c["text"].startswith("counters read blue as it stands: Balm - ")
    [c] = [c for c in held.blue.contributions if c["id"] == base.COUNTERS]
    assert c["likely"] and sorted(c["against"]) == sorted(likely)


class Inline:
    """An executor that runs each task as it is submitted, in this process:
    the pool's slices, rounds and merges without its processes."""

    def submit(self, fn, *args, **kwargs):
        future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


@pytest.mark.parametrize("playbook", ["reference", "assumptions"])
def test_the_sliced_board_agrees_with_one_process(monkeypatch, synthetic_world, tmp_path,
                                                  playbook):
    """Every search cut into four slices and run inline - the bounds widened,
    the standings summed, the field ranked from the merged verdicts - is the
    Board one process solves seat by seat, bit for bit, with the default
    engine on: under the reference playbook and under assumptions alone,
    where the engine is all that scores, with red revealed and with red's
    likely six in its place. The playbook is read from its folder, as a
    worker reads it."""
    from inference import parallel, supersede
    folder = FIXTURE_PLAYBOOK
    if playbook == "assumptions":
        folder = str(tmp_path)
        for s in ASSUMPTIONS_ONLY:
            shutil.copy(os.path.join(FIXTURE_PLAYBOOK, s.id + ".md"), tmp_path)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", folder)
    in_force = catalog.load()
    brief = engine.Brief()
    assert brief.base == DEFAULT
    for draft in (Draft("Harbor Gate", side="attack"), TRACED):
        sliced = engine._board_once(
            synthetic_world, draft, catalog=in_force, brief=brief,
            workers=parallel.Workers(Inline(), 4), watch=supersede.Watch(None))
        alone = engine._board_once(
            synthetic_world, draft, catalog=in_force, brief=brief, workers=None,
            watch=supersede.Watch(None))
        assert any(c["kind"] == "base" for c in sliced.blue.contributions)
        assert timeless(sliced.to_dict()) == timeless(alone.to_dict()), draft


def test_every_base_term_cites_a_fact_the_result_carries(synthetic_world):
    """The rate and counter terms cite facts of their own, written after the
    board's; the synergy term cites the board's cohesion fact. The page reads
    them through `cited`."""
    r = engine.infer(synthetic_world, Draft("Harbor Gate", ("Mortar",), side="attack"),
                     catalog=ASSUMPTIONS_ONLY)
    board_facts = engine._board_facts(synthetic_world, r, "attack").facts
    cited = r.to_dict()["cited"]
    for c in r.contributions:
        assert c["fact"] in cited and cited[c["fact"]] == c["text"], c["id"]
    terms = {c["id"]: c for c in r.contributions}
    assert terms[base.SYNERGY]["fact"] in {f.id for f in board_facts}
    assert terms[base.RATES]["text"].startswith("blue's six on Harbor Gate: ")
    assert terms[base.COUNTERS]["text"].startswith("counters read red as it stands: Mortar")
    assert int(terms[base.RATES]["fact"][1:]) > len([f for f in board_facts if f.id[0] == "F"])


def test_a_playbook_of_assumptions_scores_by_the_engine_and_its_best_six_is_the_maximum(
        synthetic_world):
    """The shipped playbook's case: assumptions alone. Every seat scores, no
    badge reads unscored, and blue's optimal is the best of every legal six
    by the engine's terms, the tie-break after them, found by enumeration."""
    w = synthetic_world
    draft = Draft("Ember Ruins", ("Mortar",), side="")
    b = engine.board(w, draft, catalog=ASSUMPTIONS_ONLY)
    d = b.to_dict()
    for key in ("blue", "red", "current", "red_current"):
        assert d[key]["scoring"] is True and d[key]["unscored"] is None, key
    badges = d["momentum"]["badges"]
    assert badges["blue"]["label"] == "100 / 100"
    assert badges["red"]["label"] == "%d / 100" % d["momentum"]["red"]   # red's pick, filled
    objective = scoring.Objective(w, w.map("Ember Ruins"), red=heroes(w, ("Mortar",)),
                                  catalog=ASSUMPTIONS_ONLY, base=DEFAULT)
    released = [h for h in w.heroes.values() if h.released]
    sixes = [
        scoring.Candidate(six) for six in itertools.combinations(released, 6)
        if sum(1 for h in six if h.role == "tank") <= 2]
    ranked = sorted((objective.score(objective.prepare(c), detail=False) for c in sixes),
                    key=lambda c: (-c.score, -c.tiebreak, sorted(c.names)))
    assert sorted(b.blue.blue) == sorted(ranked[0].names)
    assert b.blue.score == pytest.approx(ranked[0].score) and ranked[0].score > ranked[1].score
    assert b.blue.alternatives[0]["score"] == pytest.approx(ranked[1].score, abs=1e-3)


def test_a_derived_edge_counts_half_a_wiki_edge_and_the_fact_names_it(synthetic_world):
    """The kit derives Mortar answering Kite on a pair the wiki leaves out:
    against red's Mortar a six holding Kite takes DERIVED_WEIGHT back, where
    the wiki's Anvil over Mortar gives WIKI_WEIGHT in; the counter fact names
    the derived edge with its mechanism and numbers, and a derived edge on a
    pair the wiki reads either way counts nothing."""
    w = synthetic_world
    kite, mortar, anvil = w.hero("Kite"), w.hero("Mortar"), w.hero("Anvil")
    fired = (Fired("antiair", 1.0, "hitscan against a flier", "Longshot, hitscan, 60 m"),)
    w.derived[(kite.id, mortar.id)] = DerivedEdge(
        winner=mortar.id, loser=kite.id, score=1.0, net=1.0, fired=fired)
    w.derived[(anvil.id, mortar.id)] = DerivedEdge(      # the wiki reads Anvil over Mortar
        winner=mortar.id, loser=anvil.id, score=1.0, net=1.0, fired=fired)
    six = ("Anvil", "Kite", "Needle", "Sorrel", "Balm", "Tansy")
    _, cand = prepared(w, "Harbor Gate", ("Mortar",), six)
    assert (cand.terms.answers, cand.terms.exposures) == (
        counters.WIKI_WEIGHT, counters.DERIVED_WEIGHT) == (2, 1)
    [c] = [c for c in cand.contributions if c["id"] == base.COUNTERS]
    assert c["derived"] == [
        "Mortar answers Kite - derived: hitscan against a flier (Longshot, hitscan, 60 m)"]
    fs = FactSet(Draft("Harbor Gate", ("Mortar",), six))
    fact = base.write_counters_fact(
        fs, seat="blue", map_name="Harbor Gate", against=c["against"], likely=False,
        answers=c["answers"], exposures=c["exposures"], derived=c["derived"])
    assert fact.text.endswith("(+1), a wiki edge 2 and a derived one 1; Mortar answers Kite -"
                              " derived: hitscan against a flier (Longshot, hitscan, 60 m)")


def test_the_stamp_holds_a_derived_edges_weight_against_a_wiki_edges():
    stamped = base.stamp(base.DEFAULT)
    assert stamped is not None and stamped["derived"] == 0.5 and stamped["counter"] == W_COUNTER
    assert base.stamp(OFF) is None
