"""infer(), evaluate() and board(): the solver plus the facts it cites.

    infer(world, "King's Row", red=["Zarya", "Pharah"], blue=["Ana"], side="attack")

returns the optimal six around the locked picks, each pick with the facts
that justify it (the board the UI layer would show for map + red + the
six), the score broken down per strategy, and the alternatives.
board() does it for both seats - blue's absolute optimal, red around
its revealed ones, on opposite sides of a sided map - and scores the
current blue picks as they stand.
"""

import concurrent.futures
import hashlib
import multiprocessing
import os
import pickle
import threading
import time
from collections import namedtuple
from collections.abc import Sequence
from concurrent.futures.process import BrokenProcessPool

from inference import catalog as catalog_module
from inference.catalog import Strategy
from inference.solver import Candidate, Solver, evaluate_comp, legal_shapes
from ui.facts import compute
from ui.facts import engine as facts_engine
from ui.facts.compute import TEAM_SIZE, is_sided, opposite
from ui.facts.model import ROLES, World


def _pct(score, best):
    """A score as a share of the board's best, 0-100: the optimal six is 100,
    the current comp its percentage of blue's optimal, an alternative its
    share of the winner. A best at or below zero makes the scale meaningless,
    so only the best itself scores 100 there."""
    if best <= 0:
        return 100 if score >= best else 0
    return max(0, min(100, round(100.0 * score / best)))


UNSCORED = ("unscored - the playbook in force holds no heuristic, scored constraint or soft"
            " limit, so every legal six ties at zero; add one and the board scores")


def _unscored(result):
    """Why this result carries no share of a best, or None when it does. The
    optimal six is 100 by definition - it is the reference, and scored
    always; any other comp reads unscored when nothing can be a share of
    anything: the playbook holds no term that scores, or none of its terms
    applies to this board (a heuristic waiting on its `when`), so the best
    six itself sums to zero."""
    if result.kind == "infer":
        return None
    return _waiting(result)


def _waiting(result):
    """The reason nothing on this board scores, or None: read off any result,
    the optimal included (a seat with no picks has no comp to read it from)."""
    if not catalog_module.has_scoring_terms(result.catalog):
        return UNSCORED
    best = result.best if result.best is not None else result.score
    if best > 0:
        return None
    by_id = {h.id: h for h in result.catalog}
    waiting = []
    for c in result.contributions:
        h = by_id.get(c["id"])
        if h is None:
            continue
        if c["applies"] and h.form != "limit":   # terms apply: the best is just not above zero
            return ("unscored on this board - the optimal six scores %.2f, not above zero,"
                    " so no comp is a share of it" % best)
        if not c["applies"]:
            waiting.append("%s waits for %s" % (h.name, h.when.source) if h.when else h.name)
    return ("unscored on this board - no scoring strategy applies yet"
            + (": " + "; ".join(waiting) if waiting else ""))


def _finish(result, best):
    result.best = best
    scoring = _unscored(result) is None
    for alt in result.alternatives:
        alt["normalized"] = _pct(alt["score"], best) if scoring else None


class Result:
    def __init__(self, kind, map_name, red, blue, locked, catalog, bans=(), side="",
                 seat="blue"):
        self.kind, self.map_name = kind, map_name
        self.red, self.blue, self.locked = red, blue, locked
        self.bans, self.side, self.seat = list(bans), side, seat
        self.partial = False
        self.catalog = catalog
        self.score = 0.0
        self.picks = []
        self.contributions = []
        self.violations = []
        self.alternatives = []
        self.facts = None
        self.considered = 0
        self.seconds = 0.0
        self.rank = None
        self.playstyle = ""
        self.best = None            # the board's best score: what 100 means here
        # the Solver that produced this result, set by infer(): current() scores a
        # partial team against the bounds its seat's optimal search froze
        self.solver = None
        # the assumptions - nothing to score: what the agent reconciles the
        # facts against beyond the arithmetic
        self.considerations = [{"id": h.id, "name": h.name}
                               for h in catalog if h.kind == "assumption"]
        # drafts: name, kind and prose only - shown, not scored, until /strategy
        self.pending = [h.id for h in catalog if h.pending]

    def to_dict(self, include_facts=False):
        cited = {}
        if self.facts is not None:
            ids = {fid for p in self.picks for fid in p["evidence"]}
            ids |= {c["fact"] for c in self.contributions if c.get("fact")}
            cited = {f.id: f.text for f in self.facts.facts if f.id in ids}
        unscored = _unscored(self)
        scoring = unscored is None
        return {"kind": self.kind, "seat": self.seat, "map": self.map_name,
                "red": self.red, "blue": self.blue, "locked": self.locked,
                "bans": self.bans, "side": self.side, "partial": self.partial,
                "score": round(self.score, 3), "scoring": scoring, "unscored": unscored,
                "weights": {h.id: h.weight for h in self.catalog if h.kind == "heuristic"},
                # a partial team has no share to report: the sum runs over the picks
                # it has, so a perfectly played draft reads 16 after one pick and can
                # fall when the right third pick lands. The fill result carries the
                # number that means something - the best six reachable from here
                "normalized": (_pct(self.score, self.best if self.best is not None else self.score)
                               if scoring and not self.partial else None),
                "playstyle": self.playstyle, "picks": self.picks,
                "contributions": self.contributions, "violations": self.violations,
                "alternatives": self.alternatives, "rank": self.rank,
                "considered": self.considered, "seconds": round(self.seconds, 2),
                "strategies": catalog_module.counts(self.catalog), "cited": cited,
                "considerations": self.considerations, "pending": self.pending,
                "facts": self.facts.to_dict() if (include_facts and self.facts) else None}

    def rendered(self):
        head = "%s for %s%s%s vs %s%s%s" % (
            {"infer": "optimal comp", "evaluate": "evaluation",
             "current": "current comp", "countered": "if countered optimally",
             "fill": "your picks, the rest filled",
             "expected": "their likely starting comp"}[self.kind],
            "red" if self.seat == "red" else "blue",
            " on %s" % self.side if self.side else "",
            " on %s" % self.map_name if self.map_name else "",
            ", ".join(self.red) or "an unknown enemy",
            " (locked: %s)" % ", ".join(self.locked) if self.locked else "",
            " (banned: %s)" % ", ".join(self.bans) if self.bans else "")
        counts = catalog_module.counts(self.catalog)
        unscored = _unscored(self)
        share = ("(%d/100)" % _pct(self.score, self.best if self.best is not None else self.score)
                 if unscored is None and not self.partial else
                 "(unscored)" if unscored is not None else
                 "(partial - see the filled six for a share)")
        if self.kind == "expected":                # a likelihood, not a score
            share = "(from the map's pick rates and the synergies, no strategy read)"
        lines = [head, "  %s%s - score %.2f %s%s, %d candidates considered in %.1fs"
                 " under %d constraints, %d heuristics and %d assumptions"
                 % (", ".join(self.blue), " (%s)" % self.playstyle if self.playstyle else "",
                    self.score, share,
                    " (rank %d among the feasible field)" % self.rank
                    if self.rank else "", self.considered, self.seconds,
                    counts["constraint"], counts["heuristic"], counts["assumption"])]
        if unscored:
            lines.append("  UNSCORED: " + unscored.split(" - ", 1)[-1])
        if self.partial:
            lines.append("  PARTIAL: %d of %d picked - sums read low until the team is full"
                         % (len(self.blue), TEAM_SIZE))
        if self.violations:
            lines.append("  VIOLATES: " + ", ".join(self.violations))
        for p in self.picks:
            lines.append("  %-8s %-14s %s" % (p["role"], p["hero"] + ("*" if p["locked"] else ""),
                                            p["why"]))
        parts = ["%s %+.2f%s" % (c["id"], c["weighted"], " (need)" if c.get("need") else "")
                 for c in self.contributions
                 if c["applies"] and abs(c["weighted"]) >= 0.005]
        lines.append("  breakdown: " + " · ".join(parts))
        for i, alt in enumerate(self.alternatives, start=1):
            lines.append("  alt %d: %s (%.2f)" % (i, ", ".join(alt["blue"]), alt["score"]))
        if self.considerations:
            lines.append("  ground rules to reconcile against: " + ", ".join(
                c["id"] for c in self.considerations))
        if self.pending:
            lines.append("  drafts not yet scored (run /strategy): " + ", ".join(self.pending))
        return "\n".join(lines)


def _reasons(fs, hero_name, locked):
    """The facts that justify one pick, from the board's own FactSet - the
    facts about OUR copy of the hero: a mirror pick has facts on both sides
    (red's Tracer answers our Ana; ours partners our D.Va), and only the
    facts the FactSet filed under the seat's own side (its "blue") count."""
    why, evidence = [], []

    def own(key):
        return [f for f in fs.find(key, hero_name) if f.team in (None, "blue")]

    def cite(key, template):
        for f in own(key):
            why.append(template(f))
            evidence.append(f.id)
            return True
        return False

    cite("hero.vs_answers", lambda f: "answers %s" % ", ".join(f.value))
    partners = own("hero.with_ally")
    if partners:
        why.append("partner of %s" % ", ".join(f.value for f in partners[:3]))
        evidence.extend(f.id for f in partners[:3])
    cite("hero.map_win", lambda f: "wins %.1f%% here" % f.value)
    for f in own("hero.map_delta"):
        if f.value >= 2.5:
            why.append("map specialist (%+.1f)" % f.value)
            evidence.append(f.id)
    cite("hero.map_style_fit", lambda f: "fits the %s style" % f.value)
    cite("hero.map_strategy", lambda f: "top-%d map by rate" % f.value)
    cite("hero.vs_answered_by", lambda f: "CAUTION: answered by %s" % ", ".join(f.value))
    if not evidence:
        cite("hero.rate", lambda f: "wins %.1f%% across all ranks" % f.value["win"])
    if locked:
        why.insert(0, "locked")
    return "; ".join(why), evidence


def _fill(result, cand, fs, solver):
    result.score = cand.score
    result.contributions = cand.contributions
    result.violations = cand.violations
    result.facts = fs
    result.considered = solver.considered
    team = cand.ns["team"]
    result.playstyle = team["style_lean"] or team["style_top"] or ""
    locked = set(result.locked)
    for h in sorted(cand.heroes, key=lambda h: (ROLES.index(h.role), h.name)):
        why, evidence = _reasons(fs, h.name, h.name in locked)
        result.picks.append({"hero": h.name, "role": h.role, "subrole": h.subrole,
                             "portrait": h.portrait, "locked": h.name in locked,
                             "why": why, "evidence": evidence})
    # cite the team/matchup fact behind each contribution
    by_id = {h.id: h for h in result.catalog}
    for c in result.contributions:
        h = by_id.get(c["id"])
        keys = [h.metric] if (h and h.kind == "heuristic") else []
        for e in ((h.require, h.bonus, h.penalty, h.when) if h else ()):
            if e is not None:
                keys += [n for n in e.names if n.startswith(("team.", "matchup."))]
        fact = _cited_fact(fs, keys)
        if fact is not None:
            c["fact"], c["text"] = fact.id, fact.text


def _cited_fact(fs, keys):
    """The first board fact that states one of these metrics. A fact is indexed
    under the key it is worded around and under every other metric its sentence
    carries (FactSet.add's `also`), so the lookup is the metric itself. A team
    metric is stated about blue; a matchup metric about the two sides, and one
    team metric is only ever stated in a matchup sentence."""
    for key in keys:
        for subject in ("blue", "blue vs red"):
            found = fs.find(key, subject)
            if found:
                return found[0]
    return None


def _order(heroes):
    return [h.name for h in sorted(heroes, key=lambda h: (ROLES.index(h.role), h.name))]


def _side(m, side):
    if side not in ("", "attack", "defense"):
        raise ValueError("side must be attack or defense, got %r" % side)
    return side if is_sided(m) else ""


def clamp_search(pool=None, top=None):
    """Bounds on the search: pool 2..12 candidates per role, top 1..20
    alternatives. Every door that takes the two from a caller - the MCP tools
    and the HTTP service - passes them through here, so the search is bounded
    by one definition. Junk raises ValueError, which each door already turns
    into its own refusal."""
    try:
        return max(2, min(int(pool or 6), 12)), max(1, min(int(top or 5), 20))
    except (TypeError, ValueError) as error:
        raise ValueError("pool and top must be numbers: %s" % error) from error


def infer(world: World, map_name: str | None = None, red: Sequence[str] = (),
          blue: Sequence[str] = (), bans: Sequence[str] = (), side: str = "", *,
          catalog: list[Strategy] | None = None, pool_size: int = 6, top: int = 5,
          seat: str = "blue", solved: tuple | None = None) -> "Result":
    """The optimal six for `seat` around its locked picks (`blue`) against
    the other seat's revealed picks (`red`), on `side` of a sided map.
    `solved` takes a (solver, ranked) the caller already has - a board's
    search, run across the worker pool - instead of searching here."""
    started = time.time()
    catalog = catalog or catalog_module.load()
    m, red_h, blue_h, bans_h = world.resolve(map_name, red, blue, bans)
    side = _side(m, side)
    if len(blue_h) > TEAM_SIZE:
        raise ValueError("more than %d %s picks" % (TEAM_SIZE, seat))
    result = Result("infer", m.name if m else None, [h.name for h in red_h], [],
                    [h.name for h in blue_h], catalog, [h.name for h in bans_h], side, seat)
    if solved is not None:
        solver, ranked = solved
    else:
        solver = Solver(world, m, red_h, blue_h, bans_h, side, catalog=catalog,
                        pool_size=pool_size)
        ranked = solver.solve(top=max(top, 1) + 1)
    if not ranked:
        raise ValueError("no composition satisfies the limits around the"
                         " locked %s picks - relax a constraint in inference/strategies/"
                         % seat)
    best = ranked[0]
    result.blue = _order(best.heroes)
    fs = facts_engine.generate(world, result.map_name, result.red, result.blue, result.bans,
                               side)
    _fill(result, best, fs, solver)
    result.alternatives = [{"blue": _order(c.heroes), "score": round(c.score, 3)}
                           for c in ranked[1:top + 1]]
    _finish(result, result.score)
    result.seconds = time.time() - started
    result.solver = solver
    return result


def evaluate(world: World, map_name: str | None = None, red: Sequence[str] = (),
             blue: Sequence[str] = (), bans: Sequence[str] = (), side: str = "", *,
             catalog: list[Strategy] | None = None, pool_size: int = 6,
             seat: str = "blue", swept: tuple | None = None) -> "Result":
    """A full six for `seat`, scored and ranked against the field the solver
    would have searched. `swept` takes that field from a search the caller
    already ran on this board."""
    started = time.time()
    catalog = catalog or catalog_module.load()
    m, red_h, blue_h, bans_h = world.resolve(map_name, red, blue, bans)
    side = _side(m, side)
    if len(blue_h) != TEAM_SIZE:
        raise ValueError("evaluate needs exactly %d %s picks (got %d)"
                         % (TEAM_SIZE, seat, len(blue_h)))
    result = Result("evaluate", m.name if m else None, [h.name for h in red_h],
                    [h.name for h in blue_h], [], catalog, [h.name for h in bans_h], side,
                    seat)
    target, field, rank, solver = evaluate_comp(world, m, red_h, blue_h, bans_h, side,
                                                catalog=catalog, pool_size=pool_size,
                                                swept=swept)
    fs = facts_engine.generate(world, result.map_name, result.red, result.blue, result.bans,
                               side)
    _fill(result, target, fs, solver)
    result.rank = rank
    result.alternatives = [{"blue": _order(c.heroes), "score": round(c.score, 3)}
                           for c in field[:3]]
    result.seconds = time.time() - started
    # the board's best known six is the 100, not this comp's own best rival: a
    # beaten six must not read 100 because nothing it was compared against beat it
    _finish(result, max([result.score] + [a["score"] for a in result.alternatives]))
    return result


def current(world: World, blue_result: "Result", map_name: str | None = None,
            red: Sequence[str] = (), blue: Sequence[str] = (), bans: Sequence[str] = (),
            side: str = "", *, catalog: list[Strategy] | None = None, pool_size: int = 6,
            seat: str = "blue", swept: tuple | None = None) -> "Result":
    """`seat`'s current picks (`blue`, from that seat's perspective) as they
    stand against the other seat's (`red`): a full six is evaluated against
    the field; a partial team is scored with the bounds of the optimal
    search it came from, and says so. `blue_result` is that seat's infer()
    result - the partial branch reads its `.solver`."""
    if len(blue) == TEAM_SIZE:
        return evaluate(world, map_name, red, blue, bans, side, catalog=catalog,
                        pool_size=pool_size, seat=seat, swept=swept)
    # The partial branch hands the catalog to Result, which iterates it, so the
    # declared default has to be loaded the way infer() and evaluate() load
    # theirs. Both callers pass one today, so this never fired.
    catalog = catalog or catalog_module.load()
    started = time.time()
    m, red_h, blue_h, bans_h = world.resolve(map_name, red, blue, bans)
    side = _side(m, side)
    result = Result("current", m.name if m else None, [h.name for h in red_h],
                    [h.name for h in blue_h], [h.name for h in blue_h], catalog,
                    [h.name for h in bans_h], side, seat)
    result.partial = True
    if not blue_h:
        result.seconds = time.time() - started
        return result
    solver = blue_result.solver
    if solver is None:
        raise ValueError("current() scores a partial team against the bounds of its"
                         " seat's optimal search: blue_result must be an infer() result,"
                         " which carries the solver that drew them")
    result.best = blue_result.score
    cand = solver.prepare(Candidate(blue_h))
    solver.score(cand)
    fs = facts_engine.generate(world, result.map_name, result.red, result.blue, result.bans,
                               side)
    _fill(result, cand, fs, solver)
    result.seconds = time.time() - started
    return result


class Board:
    """Both seats of one draft: the seven Results board() solves, the verdict
    and prose it reads off them, and the shape limits the roster enforces.
    Carries the same to_dict()/rendered() pair as Result, so the shells hand a
    board to the caller the way they hand a single seat."""

    def __init__(self, map_name, side, bans, blue, red, current, red_current, fill,
                 countered, momentum, plan, shapes, expected):
        self.map_name, self.side, self.bans = map_name, side, bans
        self.blue, self.red = blue, red
        self.current, self.red_current = current, red_current
        self.fill, self.countered = fill, countered
        self.momentum, self.plan = momentum, plan
        self.shapes, self.expected = shapes, expected

    def to_dict(self):
        """The board as JSON-ready data."""
        return {"map": self.map_name, "side": self.side, "bans": self.bans, "plan": self.plan,
                "blue": self.blue.to_dict(), "red": self.red.to_dict(),
                "current": self.current.to_dict(), "red_current": self.red_current.to_dict(),
                "countered": self.countered.to_dict() if self.countered else None,
                "fill": self.fill.to_dict() if self.fill else None, "momentum": self.momentum,
                "shapes": self.shapes,
                "expected": self.expected.to_dict()}

    def rendered(self):
        parts = ["game plan:\n" + self.plan]
        parts += [r.rendered() for r in (self.blue, self.red, self.current, self.red_current)
                  if r.blue or r.kind != "current"]
        if self.fill:
            parts.append(self.fill.rendered())
        if self.countered:
            parts.append(self.countered.rendered())
        parts.append(self.expected.rendered())
        return "\n\n".join([*parts, "momentum: " + self.momentum["verdict"]])


def _momentum(cur, red_cur, countered, blue_r=None, red_r=None, fill=None):
    """Who the picks favour, read off the two current comps on their own
    optimals' scales: blue's share of its best counter to red's selection,
    red's share of its best counter to blue's. A seat with no picks has no
    contributions to name a waiting strategy by, so its reason is read off
    its optimal instead.

    A half-drafted seat is read through its fill - the best six reachable from
    what it has. Scoring the picks alone sums over a smaller team, so a
    perfectly played draft would read low and could fall when the right pick
    lands; that measures how many picks are in, not how good they are."""
    blue_why = _unscored(cur) if cur.blue or blue_r is None else _waiting(blue_r)
    red_why = _unscored(red_cur) if red_cur.blue or red_r is None else _waiting(red_r)
    if blue_why and red_why:                       # neither seat can be a share of anything
        return {"blue": None, "red": None, "countered": None, "partial": False,
                "verdict": blue_why}
    # A half-drafted seat is read through its fill where one was computed - the
    # best six reachable from its picks. Scoring the picks alone sums over a
    # smaller team, so a well-played draft reads low and can fall when the right
    # pick lands. Red has no fill, so its half-drafted share keeps that bias: the
    # seat with more picks is flattered. Known, and not fixed here.
    blue_now = fill if (fill is not None and cur.partial and cur.blue) else cur
    n = _pct(blue_now.score, blue_now.best) if cur.blue and not blue_why else None
    m = _pct(red_cur.score, red_cur.best) if red_cur.blue and not red_why else None
    k = (_pct(countered.score, countered.best)
         if countered is not None and countered.blue and not _unscored(countered) else None)
    out = {"blue": n, "red": m, "countered": k,
           "partial": bool((cur.blue and cur.partial) or (red_cur.blue and red_cur.partial))}
    # fight odds: the two shares pitted against each other - each side's share of
    # the two shares' sum, so the pair reads as a split of 100; defined only when
    # both seats score
    out["odds"] = ({"blue": round(100.0 * n / (n + m)), "red": 100 - round(100.0 * n / (n + m))}
                   if n is not None and m is not None and n + m > 0 else None)
    short = lambda why: "unscored: " + why.split(": ", 1)[-1]   # noqa: E731
    if (blue_why and cur.blue) or (red_why and red_cur.blue):   # one seat scores, the other waits
        sides = ["blue " + (short(blue_why) if blue_why else "%d / 100 of its optimal" % n)
                 if cur.blue else "no blue picks yet",
                 "red " + (short(red_why) if red_why else "%d / 100 of its best counter" % m)
                 if red_cur.blue else "no red picks revealed yet"]
        out["verdict"] = "; ".join(sides)
    elif n is None and m is None:
        out["verdict"] = "no picks yet on either side"
    elif n is None:
        out["verdict"] = ("red has revealed picks and blue has none:"
                          " red %d / 100 of its best counter" % m)
    elif m is None:
        out["verdict"] = "no red picks revealed yet: blue %d / 100 of its optimal" % n
    else:
        gap = n - m
        if abs(gap) < 5:
            out["verdict"] = "even - blue %d, red %d" % (n, m)
        elif gap > 0:
            out["verdict"] = "blue ahead by %d - blue %d, red %d" % (gap, n, m)
        else:
            out["verdict"] = "red ahead by %d - blue %d, red %d" % (-gap, n, m)
        if out["partial"]:
            out["verdict"] += " (partial picks)"
        if out["odds"]:
            out["verdict"] += "; fight odds blue %d%%, red %d%%" % (out["odds"]["blue"],
                                                                    out["odds"]["red"])
    if k is not None:
        out["verdict"] += "; if red plays its best counter, your picks hold %d / 100" % k
    return out


MODE_GROUND = {
    "Control": "one point in three arenas - whoever holds the point's ground holds the round",
    "Escort": "a payload path with a choke between phases - the fight moves with the cart",
    "Hybrid": "a capture point and then the payload path - the first fight is at the point,"
              " the rest along the route",
    "Push": "one long lane with the robot - fights follow the barricade and regrouping"
            " costs distance",
    "Flashpoint": "five points across a wide map - long rotations between fast fights, so"
                  " arriving first and together matters",
}
STYLE_PLAY = {
    "dive": "pick a target, commit together with mobile tanks and flankers, and get out with"
            " supports who can follow",
    "brawl": "hold ground as a group, sustain the front line with area healing, and win the"
             " close-range trade",
    "poke": "take the long sightlines, chip from range with healers who reach, and make them"
            " walk into damage",
}
SAME_LEAN = {
    "dive": "both sides dive - peel for your backline first, then commit on theirs",
    "brawl": "both sides fight at close range - the side that sustains longer and trades"
             " ultimates better wins the ground",
    "poke": "both sides chip from range - take the sightlines first and win the range trade",
}
THEIR_LEAN = {
    "dive": "expect them to commit on one of your backline - stay together, peel, and punish"
            " the divers as they land",
    "brawl": "they want to hold ground as a group - do not walk into their front line; split"
             " them or out-range them",
    "poke": "they want to chip from range - close the distance behind cover or take the"
            " sightlines first",
}
SIDE_PLAY = {
    "attack": "attacking: you have to break their hold, so take the high ground before you"
              " commit and go in together",
    "defense": "defending: the ground is yours - set up on the high ground and make them"
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


def _and(items):
    items = list(items)
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def _sentence(text):
    text = text.strip().rstrip(".")
    return text[:1].upper() + text[1:] + "."


FAMILY_SIZE = 5     # heroes the plan names per role


def _family(world, m, style, role, bans):
    """A style's heroes in one role, by the wiki's playstyle tags: released
    and unbanned, fewest tags first, then best win rate here."""
    out = {h.name for h in map(world.hero, bans) if h is not None}

    def rate(h):
        return (h.map_win(m.id) if m is not None else None) or h.win or 0.0
    heroes = [h for h in world.heroes.values()
              if h.role == role and style in h.styles and h.released and h.name not in out]
    return [h.name for h in sorted(heroes, key=lambda h: (len(h.styles), -rate(h), h.name))
            ][:FAMILY_SIZE]


def _plan(world, m, side, bans, red_h, blue_r):
    """The game plan in prose - the ground, what to play on it, what red's
    picks mean (their likely six until one is revealed), the family of heroes
    to stay in when you stray from the six, and what the six is built for -
    from the same facts and strategies the solver scored, so that picks can be
    tailored toward the optimal without matching it. Ends with what it rests on."""
    lines = []
    # the ground
    if m is None:
        read = ["No map yet, so this is the meta's best six: what is winning right now, built"
                " to fit together."]
    else:
        ground = MODE_GROUND.get(m.mode, "the fight follows the objective")
        read = ["%s is a %s map: %s." % (m.name, m.mode, ground)]
        # the ground the wiki's article stresses: the map.terrain facts above the ordinary map
        facts = blue_r.facts
        stressed = [f.value["feature"] for f in (facts.find("map.terrain", m.name)
                                                 if facts is not None else ())
                    if f.value["z"] > 0][:TERRAIN_NAMED]
        if stressed:
            read.append("The wiki's article stresses %s."
                        % _and(TERRAIN_GROUND[f] for f in stressed))
        # the stages whose own text stresses a feature: the map.stage_terrain facts
        staged = sorted((facts.find("map.stage_terrain", m.name) if facts is not None else ()),
                        key=lambda f: -f.value["features"][0]["z"])[:STAGES_NAMED]
        staged = [(f.value["stage"], _and(TERRAIN_GROUND[x["feature"]]
                                          for x in f.value["features"]))
                  for f in sorted(staged, key=lambda f: m.stages.index(f.value["stage"]))]
        if staged:
            read.append("; ".join(("%s has the %s" if i == 0 else "%s the %s") % pair
                                  for i, pair in enumerate(staged)) + ".")
        if side in SIDE_PLAY:
            read.append("You are " + SIDE_PLAY[side] + ".")
    # what to play
    map_style = m.style_top if m is not None else ""
    lean = blue_r.playstyle
    if map_style and lean == map_style:
        read.append("The map rewards %s and the six leans into it: %s." % (lean, STYLE_PLAY[lean]))
    elif map_style and lean:
        read.append("The map rewards %s, but %sthe six leans %s: %s."
                    % (map_style, "against this red " if red_h else "", lean,
                       STYLE_PLAY.get(lean, "play to its picks")))
    elif lean:
        read.append("The six leans %s: %s." % (lean, STYLE_PLAY.get(lean, "play to its picks")))
    elif map_style:
        read.append("The map rewards %s: %s." % (map_style, STYLE_PLAY[map_style]))
    lines.append(" ".join(read))
    # them
    if red_h:
        n = len(red_h)
        theirs = compute.team_metrics(world, red_h, m, [])
        red_lean = theirs["style_lean"] or theirs["style_top"] or ""
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
        answered = {}
        for p in blue_r.picks:
            for part in p["why"].split("; "):
                if part.startswith("answers "):
                    for name in part[len("answers "):].split(", "):
                        answered.setdefault(name, []).append(p["hero"])
        names = [h.name for h in red_h]
        pairs = sorted(((k, v) for k, v in answered.items() if k in names),
                       key=lambda kv: -len(kv[1]))
        if pairs:
            them += " " + _sentence("; ".join(
                "%s answer%s %s" % (_and(v), "" if len(v) > 1 else "s", k)
                                              for k, v in pairs[:4]))
        missing = [k for k in names if k not in answered]
        if missing:
            them += " Nobody in the six answers %s - respect %s." % (
                _and(missing), "them" if len(missing) > 1 else "that pick")
        lines.append(them)
    elif blue_r.red:
        lines.append("No red pick yet: the six counters their likely six (%s)."
                     % ", ".join(blue_r.red))
    # the family to stay in
    if lean:
        parts = []
        for role, plural in (("tank", "Tanks"), ("damage", "Damage"), ("support", "Supports")):
            names = _family(world, m, lean, role, bans)
            if names:
                parts.append("%s: %s." % (plural, ", ".join(names)))
        if parts:
            lines.append("If you stray from the six, stay in its family. " + " ".join(parts))
    # what it is built for
    names = {h.id: h.name for h in blue_r.catalog}
    # not the shape every legal six pays, nor a rule named for another style
    # ("Dive the pocket" on a poke six); a rule on the map's style is about the map
    skip = {h.id for h in blue_r.catalog
            if (h.kind == "constraint" and h.category == "shape")
            or (h.name.split()[0].lower() in STYLE_PLAY and h.name.split()[0].lower() != lean
                and not (h.when and "map.style_top" in h.when.names))}
    top = sorted((c for c in blue_r.contributions
                  if c["applies"] and c["weighted"] > 0.05
                  and c["id"] not in skip),
                 key=lambda c: -c["weighted"])[:4]
    if top:
        lines.append("Above all: "
                     + "; ".join(names.get(c["id"], c["id"]).lower() for c in top) + ".")
    # what it rests on
    basis = ["the rates and counters"]
    if m is not None:
        basis.append("the map")
    if side:
        basis.append("the side")
    if bans:
        basis.append("%d ban%s" % (len(bans), "" if len(bans) == 1 else "s"))
    if red_h:
        basis.append("red's %d revealed pick%s" % (len(red_h), "" if len(red_h) == 1 else "s"))
    lines.append("Based on: %s." % ", ".join(basis))
    return "\n".join(lines)


# --- the board's search, split across workers ------------------------------
#
# CPython holds the GIL for this pure-Python work, so parallelism means
# processes: a pool of workers, spawned once and kept - the servers that call
# this are threaded, and forking a threaded process is unsafe. Each search
# runs in four rounds, a slice per worker: the reference sample, for the low
# and high each heuristic takes on this board; the sample again, scored under
# those bounds, for each hero's standing, which ranks the pools; the
# enumeration, prepared and scored; then one worker ranks and refines the
# merged field. Only verdicts cross - hero ids, score, tie-break - and slices
# partition their round, so nothing depends on how the work was split.
#
# The board runs four searches. Blue's and red's go first. The fill is blue's
# board (same map, side, enemies and bans), so it takes blue's bounds and
# standing and draws no sample of its own; the countered case follows red's six. A full
# six is ranked against the field its seat's search already swept.
#
# The world crosses as bytes pickled once and cached per worker; so is the
# playbook, reread when a file changes. Off with COUNTRIX_PARALLEL=0,
# on one core, or with a catalog the caller supplied (a worker loads the
# playbook from its files).

PARALLEL = os.environ.get("COUNTRIX_PARALLEL", "1").lower() not in ("0", "no", "false")
WORKER_CEILING = 12          # a worker holds about 70 MB, and past a dozen slices the
                             # rounds' own overhead eats what a finer slice saves


def _worker_count():
    """Six workers, or one per core where there are more, capped at
    WORKER_CEILING. COUNTRIX_WORKERS overrides."""
    override = os.environ.get("COUNTRIX_WORKERS", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    return max(6, min(os.cpu_count() or 1, WORKER_CEILING))


WORKERS = _worker_count()
_pool = None
_pool_lock = threading.Lock()


def _workers():
    """The pool, created on first use. Spawned, not forked."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = concurrent.futures.ProcessPoolExecutor(
                max_workers=WORKERS, mp_context=multiprocessing.get_context("spawn"))
        return _pool


def _drop_workers():
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def parallel_available(catalog=None):
    """Whether board() splits its search across workers here. A caller's own
    catalog keeps the solve in this process: a strategy carries compiled
    expressions, which do not pickle, so a worker can only rebuild the playbook
    by reading the files (_playbook) and applying the weights on top."""
    return PARALLEL and catalog is None and (os.cpu_count() or 1) > 1


def warm(world=None):
    """Start the workers now, so the first board does not pay for it: they
    read the playbook, and take a copy of the world when one is given.
    Returns the number started, 0 when the board runs sequentially here."""
    if not parallel_available():
        return 0
    pool = _workers()                          # more tasks than workers, so each gets one
    args = _world_blob(world) if world is not None else (None, None)
    futures = [pool.submit(_prime, *args) for _ in range(WORKERS * 3)]
    concurrent.futures.wait(futures)
    return WORKERS


def _prime(token=None, data=None):
    """In a worker: read the playbook and hold the world, so the first slice
    does not."""
    _playbook()
    if token is not None:
        _world(token, data)
    return os.getpid()


# --- what crosses the boundary ---------------------------------------------

_blob_lock = threading.Lock()
_blob = (None, None, None)              # the world, its token, its bytes


def _world_blob(world):
    """The world pickled once for a run of tasks: the bytes, and their digest
    as the token the workers cache it under - a server loads a fresh world per
    request, and the same rows keep the workers' copy. The world is held here
    too, so the identity check cannot be fooled by a later object at the same
    address."""
    global _blob
    with _blob_lock:
        held, token, data = _blob
        if held is not world:
            data = pickle.dumps(world, pickle.HIGHEST_PROTOCOL)
            token = hashlib.sha1(data, usedforsecurity=False).hexdigest()
            _blob = (world, token, data)
        return token, data


_held_world = (None, None)              # in a worker: the token and the world
_held_playbook = (None, None)           # in a worker: the files' stamp and the catalog


def _world(token, data):
    global _held_world
    if _held_world[0] != token:
        _held_world = (token, pickle.loads(data))
    return _held_world[1]


def _playbook():
    """The playbook, read once per worker and again whenever a file changes."""
    global _held_playbook
    directory = catalog_module.strategies_dir()
    stamp = sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size)
                   for e in os.scandir(directory)
                   if e.name.endswith(".md")) if os.path.isdir(directory) else None
    if stamp is None or _held_playbook[0] != stamp:
        _held_playbook = (stamp, catalog_module.load(directory))
    return _held_playbook[1]


def _verdict(cand):
    """A candidate as the pool ships it: who is in it, what it scored, how it
    breaks a tie. Everything else is rebuilt where it is needed."""
    return (tuple(h.id for h in cand.heroes), cand.score, cand.tiebreak)


def _revive(world, verdict):
    ids, score, tiebreak = verdict
    cand = Candidate([world.heroes[i] for i in ids])
    cand.score, cand.tiebreak, cand.raw = score, tiebreak, None
    return cand


# the board one worker solves, named: it crosses the pool as a plain tuple does
Spec = namedtuple("Spec", "map_name enemy locked pool_size bans side")


def _solver(world, catalog, spec):
    m, red_h, locked_h, bans_h = world.resolve(spec.map_name, spec.enemy, spec.locked,
                                               spec.bans)
    return Solver(world, m, red_h, locked_h, bans_h, _side(m, spec.side),
                  catalog=catalog, pool_size=spec.pool_size)


def _bounds(token, data, spec, weights, index, count):
    """One slice of the reference sample, in a worker: the low and high it
    sees for each heuristic."""
    world = _world(token, data)
    solver = _solver(world, catalog_module.weighted(_playbook(), weights), spec)
    return solver.reference_bounds(index, count)


def _standing(token, data, spec, weights, bounds, index, count):
    """One slice of the reference sample scored under the merged bounds, in a
    worker: each hero's tally in it."""
    world = _world(token, data)
    solver = _solver(world, catalog_module.weighted(_playbook(), weights), spec)
    solver.adopt_bounds(bounds)
    return solver.reference_standing(index, count)


def _add(tally, part):
    for hid, (total, n) in part.items():
        seen = tally.setdefault(hid, [0, 0])
        seen[0] += total
        seen[1] += n
    return tally


def _widen(bounds, part):
    for hid, (lo, hi) in part.items():
        seen = bounds.get(hid)
        bounds[hid] = (min(lo, seen[0]), max(hi, seen[1])) if seen else (lo, hi)
    return bounds


def _sweep(token, data, spec, weights, bounds, standing, index, count):
    """One slice of one search, in a worker."""
    world = _world(token, data)
    solver = _solver(world, catalog_module.weighted(_playbook(), weights), spec)
    solver.adopt_bounds(bounds, standing)
    size, feasible = solver.sweep(index, count)
    return size, [_verdict(c) for c in feasible]


def _rank(token, data, spec, weights, bounds, standing, verdicts, top):
    """The tail of a split search, in a worker: the merged field ranked and
    refined. -> (the winners, how many candidates refining added)."""
    world = _world(token, data)
    solver = _solver(world, catalog_module.weighted(_playbook(), weights), spec)
    solver.adopt_bounds(bounds, standing)
    ranked = solver.rank([_revive(world, v) for v in verdicts], top)
    return [_verdict(c) for c in ranked], solver.considered


class _Split:
    """One search, split across the pool, a round at a time: the reference
    sample, then the enumeration, then the tail. A caller starts several and
    walks them through the rounds together, so the pool stays full."""

    def __init__(self, pool, world, catalog, spec, weights, top, slices, bounds=None,
                 standing=None):
        self.pool, self.world, self.catalog = pool, world, catalog
        self.spec, self.weights, self.top = spec, weights, top
        self.bounds, self.size, self.verdicts = bounds, 0, []
        self.standing, self.tallies = standing, None
        self.token, self.data = _world_blob(world)
        self.count = slices
        self.scale = None if bounds is not None else [
            pool.submit(_bounds, self.token, self.data, spec, weights, i, slices)
            for i in range(slices)]
        self.slices = self.tail = None

    def rank_roster(self):
        """Take the scale the slices drew, and send the sample out again to be
        scored under it: each hero's standing, which ranks the pools."""
        if self.scale is not None:
            self.bounds = {}
            for future in self.scale:
                _widen(self.bounds, future.result())
            self.scale = None
        if self.standing is None and self.tallies is None:
            self.tallies = [self.pool.submit(_standing, self.token, self.data, self.spec,
                                             self.weights, self.bounds, i, self.count)
                            for i in range(self.count)]

    def sweep(self):
        """Take the standing, and send the enumeration out."""
        self.rank_roster()
        if self.tallies is not None:
            self.standing = {}
            for future in self.tallies:
                _add(self.standing, future.result())
            self.tallies = None
        self.slices = [self.pool.submit(_sweep, self.token, self.data, self.spec, self.weights,
                                        self.bounds, self.standing, i, self.count)
                       for i in range(self.count)]

    def merge(self):
        """Collect the slices and send the merged field off to be ranked."""
        self.verdicts = []
        for future in self.slices:
            self.size, part = future.result()
            self.verdicts.extend(part)
        self.tail = self.pool.submit(_rank, self.token, self.data, self.spec, self.weights,
                                     self.bounds, self.standing, self.verdicts, self.top)

    def _solver(self):
        solver = _solver(self.world, self.catalog, self.spec)
        solver.adopt_bounds(self.bounds, self.standing)
        return solver

    def solved(self):
        """(solver, ranked), as Solver.solve() would have returned them."""
        winners, refined = self.tail.result()
        solver = self._solver()
        solver.considered = self.size + refined
        return solver, [solver.hydrate(_revive(self.world, v)) for v in winners]

    def swept(self):
        """(solver, field size, every feasible candidate), as Solver.sweep()
        would have left them: what a six is ranked against."""
        return (self._solver(), self.size,
                [_revive(self.world, v) for v in self.verdicts])


COUNTERED_POOL = 4          # a what-if: a smaller field is enough


def _countered(world, map_name, red_optimal, blue, bans=(), side="", *,
               catalog=None, pool_size=6, top=5, solved=None, swept=None):
    """Blue's picks against red's optimal six: how they hold if red answers
    perfectly."""
    hypothetical = min(pool_size, COUNTERED_POOL)
    against = infer(world, map_name, red_optimal, [], bans, side, catalog=catalog,
                    pool_size=hypothetical, top=top, solved=solved)
    result = current(world, against, map_name, red_optimal, blue, bans, side,
                     catalog=catalog, pool_size=hypothetical, swept=swept)
    result.kind = "countered"
    _finish(result, against.score)
    return result


def board(world: World, map_name: str | None = None, red: Sequence[str] = (),
          blue: Sequence[str] = (), bans: Sequence[str] = (), side: str = "", *,
          catalog: list[Strategy] | None = None, pool_size: int = 6, top: int = 5,
          weights: dict[str, float] | None = None) -> "Board":
    """The whole board in one pass, at whatever stage the draft is - no map
    (the meta's best six), a map, a map and a side, bans, red's picks as
    they reveal:

        blue         blue's optimal six: the best counter to red's selection
                     as revealed - or, before they reveal a pick, to their
                     likely six - on this map, side and bans; blue's own
                     picks never constrain it
        red          red's optimal six: their best counter to blue's
                     selection, on the other side - the scale red's current
                     comp is measured on
        current      blue's picks as they stand, scored against red's
                     selection on blue's optimal's scale
        red_current  red's picks as they stand, scored against blue's
                     selection on red's optimal's scale
        countered    blue's picks against red's optimal six - how you hold
                     if they answer you perfectly (None without blue picks)
        fill         blue's locked picks with the empty slots filled by the
                     solver - the best six that keeps what you hold, on
                     blue's optimal's scale (None unless one to five are locked)
        momentum     the verdict from the two current comps
        plan         the game plan in prose, from the same facts
        shapes       the (tanks, damage, supports) triples the playbook's shape
                     limits allow - what the roster enforces as you pick
        expected     red's likely six from the data alone - a two-two-two from
                     the map's pick rates and the wiki's synergies, past the
                     bans - static for the board, no strategy read; what the
                     comps tab shows for red and what blue counters until red
                     reveals a pick

    `weights` ({heuristic id: 0..10}) overrides the files' weights for this
    board only - the playbook tab's sliders; the files stay as they are and
    every result says the weights it was scored under.
    """
    parallel = parallel_available(catalog)
    catalog = catalog_module.weighted(catalog or catalog_module.load(), weights)
    m, red_h, _, bans_h = world.resolve(map_name, red, blue, bans)
    side = _side(m, side)
    # red's likely six - the map and the meta alone, past the bans - is static
    # for the board; until red reveals a pick it is what blue's seat counters.
    # A Result like every other seat: its picks carry the reason each rests on
    likely = compute.expected_picks(world, m, [], bans_h)
    expected = Result("expected", m.name if m else None, [], [p["hero"] for p in likely], [],
                      catalog, bans, side, seat="red")
    expected.picks = [dict(p, evidence=[]) for p in likely]
    enemy = list(red) if red else expected.blue
    blue_list, bans_list = list(blue), list(bans)
    wants_fill = 0 < len(blue_list) < TEAM_SIZE
    # One orchestration, run once. Across the pool the four searches are split
    # and handed to the same six calls; in this process every split is None and
    # each call searches for itself. A worker dying anywhere in the pooled pass
    # drops the pool and runs the very same sequence here.
    for pooled in [True, False] if parallel else [False]:
        try:
            fill = countered = None
            blue_split = red_split = fill_split = countered_split = None
            if pooled:
                pool = _workers()
                want = max(top, 1) + 1
                half = max(1, WORKERS // 2)
                rest = max(1, WORKERS - half)
                blue_split = _Split(pool, world, catalog,
                                    Spec(map_name, enemy, [], pool_size, bans_list, side),
                                    weights, want, half)
                red_split = _Split(pool, world, catalog,
                                   Spec(map_name, blue_list, [], pool_size, bans_list,
                                        opposite(side)), weights, want, rest)
                blue_split.rank_roster()
                red_split.rank_roster()
                blue_split.sweep()
                red_split.sweep()
                if wants_fill:
                    # the fill is blue's board, so it takes blue's scale and draws none
                    fill_split = _Split(pool, world, catalog,
                                        Spec(map_name, enemy, blue_list, pool_size,
                                             bans_list, side),
                                        weights, want, half, blue_split.bounds,
                                        blue_split.standing)
                    fill_split.sweep()
                blue_split.merge()
                red_split.merge()
            blue_r = infer(world, map_name, enemy, [], bans, side, catalog=catalog,
                           pool_size=pool_size, top=top,
                           solved=blue_split.solved() if blue_split else None)
            red_r = infer(world, map_name, blue_list, [], bans, opposite(side),
                          catalog=catalog, pool_size=pool_size, top=top, seat="red",
                          solved=red_split.solved() if red_split else None)
            if pooled and blue_list and red_r.blue:
                countered_split = _Split(
                    pool, world, catalog,
                    Spec(map_name, red_r.blue, [], min(pool_size, COUNTERED_POOL),
                         bans_list, side),
                    weights, want, rest)
                countered_split.sweep()
            if fill_split is not None:
                fill_split.merge()
            if countered_split is not None:
                countered_split.merge()
            # a full six is ranked against the field its seat's search just swept
            cur = current(world, blue_r, map_name, enemy, blue, bans, side,
                          catalog=catalog, pool_size=pool_size,
                          swept=blue_split.swept()
                          if blue_split and len(blue_list) == TEAM_SIZE else None)
            _finish(cur, blue_r.score)             # 100 is blue's optimal, whatever you hold
            red_cur = current(world, red_r, map_name, blue, red, bans, opposite(side),
                              catalog=catalog, pool_size=pool_size, seat="red",
                              swept=red_split.swept()
                              if red_split and len(red) == TEAM_SIZE else None)
            _finish(red_cur, red_r.score)
            if wants_fill:
                fill = infer(world, map_name, enemy, blue, bans, side, catalog=catalog,
                             pool_size=pool_size, top=top,
                             solved=fill_split.solved() if fill_split else None)
            if blue_list and red_r.blue:
                countered = _countered(
                    world, map_name, red_r.blue, blue, bans, side, catalog=catalog,
                    pool_size=pool_size, top=top,
                    solved=countered_split.solved() if countered_split else None,
                    swept=countered_split.swept()
                    if countered_split and len(blue_list) == TEAM_SIZE else None)
            break
        except BrokenProcessPool:
            if not pooled:
                raise                  # nothing was pooled: the pool is not the fault
            _drop_workers()            # a worker died: this board, in this process
    if fill is not None:
        fill.kind = "fill"
        _finish(fill, blue_r.score)                # how close the best completion comes
    return Board(m.name if m else None, side, list(bans), blue_r, red_r, cur, red_cur, fill,
                 countered, _momentum(cur, red_cur, countered, blue_r, red_r, fill),
                 _plan(world, m, side, list(bans), red_h, blue_r),
                 [list(s) for s in legal_shapes(catalog)], expected)
