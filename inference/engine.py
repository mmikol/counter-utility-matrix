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
import multiprocessing
import os
import threading
import time
import types

from inference import catalog as catalog_module
from inference.solver import Candidate, Solver, evaluate_comp, legal_shapes
from ui.facts import compute
from ui.facts import engine as facts_engine
from ui.facts.compute import TEAM_SIZE, is_sided, opposite

ROLE_ORDER = {"tank": 0, "damage": 1, "support": 2}


def _pct(score, best):
    """A score as a share of the board's best, 0-100: the optimal six is 100,
    the current comp its percentage of blue's optimal, an alternative its
    share of the winner. A best at or below zero makes the scale meaningless,
    so only the best itself scores 100 there."""
    if best is None or best <= 0:
        return 100 if score >= (best if best is not None else score) else 0
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
    if getattr(result, "kind", None) == "infer":
        return None
    return _waiting(result)


def _waiting(result):
    """The reason nothing on this board scores, or None: read off any result,
    the optimal included (a seat with no picks has no comp to read it from)."""
    catalog = getattr(result, "catalog", None)
    if catalog is None:                                    # the tests' stand-ins
        return None
    if not catalog_module.scores(catalog):
        return UNSCORED
    best = result.best if getattr(result, "best", None) is not None else result.score
    if best > 0:
        return None
    by_id = {h.id: h for h in catalog}
    waiting = []
    for c in getattr(result, "contributions", []) or []:
        h = by_id.get(c.get("id"))
        if h is None or c.get("applies", True) or c.get("kind") not in ("heuristic", "constraint"):
            continue
        when = getattr(h, "when_source", None) or getattr(getattr(h, "when", None), "source", None)
        waiting.append("%s waits for %s" % (h.name, when) if when else h.name)
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
        # the assumptions - nothing to score: what the agent reconciles the
        # facts against beyond the arithmetic
        self.considerations = [{"id": h.id, "name": h.name}
                               for h in catalog if h.kind == "assumption"]
        # drafts: name, kind and prose only - shown, not scored, until /strategy
        self.pending = [h.id for h in catalog if h.pending]

    def __getstate__(self):
        """What crosses a process boundary: everything but the solver (its
        reference sample and bounds stay with the worker that used them) and
        the catalog's compiled expressions - a strategy's id, name, kind, form,
        weight and softness is all a result needs of it afterwards (the
        weights it was scored under; whether the playbook scores at all)."""
        state = dict(self.__dict__)
        state.pop("solver", None)
        state["catalog"] = [types.SimpleNamespace(id=h.id, name=h.name, kind=h.kind,
                                                  pending=getattr(h, "pending", False),
                                                  form=getattr(h, "form", None),
                                                  weight=getattr(h, "weight", None),
                                                  soft=getattr(h, "soft", False),
                                                  when_source=getattr(
                                                      getattr(h, "when", None), "source", None))
                            for h in self.catalog]
        return state

    def to_dict(self, include_facts=False):
        counts = {k: sum(1 for h in self.catalog if h.kind == k)
                  for k in catalog_module.KINDS}
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
                "weights": {h.id: getattr(h, "weight", None)
                            for h in self.catalog if h.kind == "heuristic"},
                "normalized": (_pct(self.score, self.best if self.best is not None else self.score)
                               if scoring else None),
                "playstyle": self.playstyle, "picks": self.picks,
                "contributions": self.contributions, "violations": self.violations,
                "alternatives": self.alternatives, "rank": self.rank,
                "considered": self.considered, "seconds": round(self.seconds, 2),
                "strategies": counts, "cited": cited,
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
        counts = {k: sum(1 for h in self.catalog if h.kind == k)
                  for k in catalog_module.KINDS}
        unscored = _unscored(self)
        share = ("(%d/100)" % _pct(self.score, self.best if self.best is not None else self.score)
                 if unscored is None else "(unscored)")
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
        parts = ["%s %+.2f" % (c["id"], c["weighted"]) for c in self.contributions
                 if c.get("applies") and abs(c["weighted"]) >= 0.005]
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
    cite("hero.map_strategy", lambda f: "counterpick top-%d here" % f.value)
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
    for h in sorted(cand.heroes, key=lambda h: (ROLE_ORDER[h.role], h.name)):
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


# a metric whose number rides inside another metric's fact line
FACT_ALIASES = {
    "team.coverage_share": "team.coverage", "team.unanswered": "team.coverage",
    "team.exposed_count": "team.exposed_count", "team.double_covered": "team.double_covered",
    "team.answer_edges": "team.net_edges", "team.exposure_edges": "team.net_edges",
    "team.synergy_score": "team.synergy_edges", "team.synergy_density": "team.synergy_edges",
    "team.isolated_count": "team.isolated_count", "team.max_ban_rate": "team.availability",
    "team.map_strategy_hits": "team.map_specialists", "team.heal_ratio": "team.heal_peak_supports",
    "team.ult_damage_total": "team.dmg_ults", "team.damage": "team.tanks",
    "team.supports": "team.tanks", "team.size": "team.size",
    "team.barrier_count": "team.barrier_hp", "team.style_lean": "team.style_top",
    "matchup.ult_answers": "matchup.ult_threat", "matchup.style_lean_red": "matchup.style_lean_red",
}


def _cited_fact(fs, keys):
    """The first board fact that carries one of these metrics: the key
    itself, its alias, or the key with trailing words stripped
    (team.coverage_share -> team.coverage), falling back through the list."""
    for key in keys:
        candidates = [key, FACT_ALIASES.get(key)]
        parts = key.split("_")
        while len(parts) > 1:
            parts.pop()
            candidates.append("_".join(parts))
        for candidate in candidates:
            if not candidate:
                continue
            subject = "blue" if candidate.startswith("team.") else "blue vs red"
            found = fs.find(candidate, subject)
            if found:
                return found[0]
    return None


def _order(heroes):
    return [h.name for h in sorted(heroes, key=lambda h: (ROLE_ORDER[h.role], h.name))]


def _side(m, side):
    if side not in ("", "attack", "defense"):
        raise ValueError("side must be attack or defense, got %r" % side)
    return side if is_sided(m) else ""


def infer(world, map_name=None, red=(), blue=(), top=5, pool_size=6, catalog=None,
          bans=(), side="", seat="blue"):
    """The optimal six for `seat` around its locked picks (`blue`) against
    the other seat's revealed picks (`red`), on `side` of a sided map."""
    started = time.time()
    catalog = catalog or catalog_module.load()
    m, red_h, blue_h, bans_h = world.resolve(map_name, red, blue, bans)
    side = _side(m, side)
    if len(blue_h) > TEAM_SIZE:
        raise ValueError("more than %d %s picks" % (TEAM_SIZE, seat))
    result = Result("infer", m.name if m else None, [h.name for h in red_h], [],
                    [h.name for h in blue_h], catalog, [h.name for h in bans_h], side, seat)
    solver = Solver(world, m, red_h, blue_h, catalog, pool_size, bans_h, side)
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


def evaluate(world, map_name=None, red=(), blue=(), pool_size=6, catalog=None,
             bans=(), side="", seat="blue"):
    """A full six for `seat`, scored and ranked against the field the solver
    would have searched."""
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
    target, field, rank, solver = evaluate_comp(world, m, red_h, blue_h, catalog,
                                                pool_size, bans_h, side)
    fs = facts_engine.generate(world, result.map_name, result.red, result.blue, result.bans,
                               side)
    _fill(result, target, fs, solver)
    result.rank = rank
    result.alternatives = [{"blue": _order(c.heroes), "score": round(c.score, 3)}
                           for c in field[:3]]
    result.seconds = time.time() - started
    _finish(result, max([result.score] + [a["score"] for a in result.alternatives]))
    return result


def current(world, blue_result, map_name=None, red=(), blue=(), catalog=None, bans=(),
            side="", pool_size=6, seat="blue"):
    """`seat`'s current picks (`blue`, from that seat's perspective) as they
    stand against the other seat's (`red`): a full six is evaluated against
    the field; a partial team is scored with the bounds of the optimal
    search it came from, and says so."""
    if len(blue) == TEAM_SIZE:
        return evaluate(world, map_name, red, blue, pool_size, catalog, bans, side, seat)
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
    result.best = blue_result.score
    cand = solver.prepare(Candidate(blue_h))
    solver.score(cand)
    fs = facts_engine.generate(world, result.map_name, result.red, result.blue, result.bans,
                               side)
    _fill(result, cand, fs, solver)
    result.seconds = time.time() - started
    return result


def board_dict(b):
    """The board() result as JSON-ready data."""
    return {"map": b["map"], "side": b["side"], "bans": b["bans"], "plan": b["plan"],
            "blue": b["blue"].to_dict(), "red": b["red"].to_dict(),
            "current": b["current"].to_dict(), "red_current": b["red_current"].to_dict(),
            "countered": b["countered"].to_dict() if b["countered"] else None,
            "fill": b["fill"].to_dict() if b["fill"] else None, "momentum": b["momentum"],
            "shapes": b["shapes"],
            "expected": b["expected"].to_dict()}


def board_rendered(b):
    parts = ["game plan:\n" + b["plan"]]
    parts += [r.rendered() for r in (b["blue"], b["red"], b["current"], b["red_current"])
              if r.blue or r.kind != "current"]
    if b["fill"]:
        parts.append(b["fill"].rendered())
    if b["countered"]:
        parts.append(b["countered"].rendered())
    parts.append(b["expected"].rendered())
    return "\n\n".join([*parts, "momentum: " + b["momentum"]["verdict"]])


def _momentum(cur, red_cur, countered, blue_r=None, red_r=None):
    """Who the picks favour, read off the two current comps on their own
    optimals' scales: blue's share of its best counter to red's selection,
    red's share of its best counter to blue's. A seat with no picks has no
    contributions to name a waiting strategy by, so its reason is read off
    its optimal instead."""
    blue_why = _unscored(cur) if cur.blue or blue_r is None else _waiting(blue_r)
    red_why = _unscored(red_cur) if red_cur.blue or red_r is None else _waiting(red_r)
    if blue_why and red_why:                       # neither seat can be a share of anything
        return {"blue": None, "red": None, "countered": None, "partial": False,
                "verdict": blue_why}
    n = _pct(cur.score, cur.best) if cur.blue and not blue_why else None
    m = _pct(red_cur.score, red_cur.best) if red_cur.blue and not red_why else None
    k = (_pct(countered.score, countered.best)
         if countered is not None and countered.blue and not _unscored(countered) else None)
    out = {"blue": n, "red": m, "countered": k,
           "partial": bool((cur.blue and cur.partial) or (red_cur.blue and red_cur.partial))}
    # fight odds: the two shares pitted against each other - each side's share of
    # the two shares' sum, so the pair reads as a split of 100 and the higher bar
    # holds the fight; defined only when both seats score
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


def _and(items):
    items = list(items)
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def _sentence(text):
    text = text.strip().rstrip(".")
    return text[:1].upper() + text[1:] + "."


def _hero_names(world, text):
    """The hero names in an archetype note ("winston d.va wrecking ball"),
    resolved through the roster - two-word names first."""
    tokens, out, i = text.split(), [], 0
    while i < len(tokens):
        two = world.hero(" ".join(tokens[i:i + 2])) if i + 1 < len(tokens) else None
        if two is not None:
            out.append(two.name)
            i += 2
            continue
        one = world.hero(tokens[i])
        if one is not None:
            out.append(one.name)
        i += 1
    return out


def _plan(world, m, side, bans, red_h, blue_r):
    """The game plan in prose - the ground, what to play on it, what red's
    picks mean, the family of heroes to stay in when you stray from the
    six, and what the six is built for - from the same facts and
    strategies the solver scored, so that picks can be tailored toward
    the optimal without matching it. Ends with what it rests on."""
    lines = []
    # the ground
    if m is None:
        read = ["No map yet, so this is the meta's best six: what is winning right now, built"
                " to fit together."]
    else:
        ground = MODE_GROUND.get(m.mode, "the fight follows the objective")
        read = ["%s is a %s map: %s." % (m.name, m.mode, ground)]
        note = m.styles.get(m.style_top, (None, None))[1] if m.style_top else None
        if note:
            read.append(_sentence(note))
        if side in SIDE_PLAY:
            read.append("You are " + SIDE_PLAY[side] + ".")
    # what to play
    map_style = m.style_top if m is not None else ""
    lean = blue_r.playstyle
    if map_style and lean == map_style:
        read.append("The map rewards %s and the six leans into it: %s." % (lean, STYLE_PLAY[lean]))
    elif map_style and lean:
        read.append("The map rewards %s, but against this red the six leans %s: %s."
                    % (map_style, lean, STYLE_PLAY.get(lean, "play to its picks")))
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
        them += (" lean%s %s: %s." % ("s" if n == 1 else "", red_lean, THEIR_LEAN[red_lean])) \
            if red_lean in THEIR_LEAN else " show%s no lean yet." % ("s" if n == 1 else "")
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
    # the family to stay in
    family = world.archetypes.get(lean) if lean else None
    if family:
        parts = []
        for role, plural in (("tank", "tanks"), ("damage", "damage"), ("support", "supports")):
            _slots, note = family.get(role, (None, None))
            if not note:
                continue
            desc, _, roster = note.partition(":")
            names = _hero_names(world, roster) if roster else []
            parts.append("%s: %s%s." % (plural.capitalize(), desc.strip(),
                                          " (%s)" % ", ".join(names) if names else ""))
        if parts:
            lines.append("If you stray from the six, stay in its family. " + " ".join(parts))
    # what it is built for
    names = {h.id: h.name for h in blue_r.catalog}
    top = sorted((c for c in blue_r.contributions
                  if c.get("applies") and c.get("weighted", 0) > 0.05),
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


# --- the board's independent solves, in parallel ---------------------------
#
# CPython holds the GIL for this pure-Python work, so parallelism means
# processes: a small pool of workers, started once per process and kept, each
# handed the world (0.6 MB, a few ms to pickle) and the names on a board. Blue's
# optimal and red's counter do not depend on each other; each worker also
# scores that seat's current comp, which needs the solver's scale and so stays
# where the solver is. The parent solves the fill meanwhile and the pessimistic
# case after. Off with COUNTER_MATRIX_PARALLEL=0, on one core, or with a
# catalog the caller supplied (a worker loads the playbook from its files).

PARALLEL = os.environ.get("COUNTER_MATRIX_PARALLEL", "1").lower() not in ("0", "no", "false")
WORKERS = 2
_pool = None
_pool_lock = threading.Lock()


def _workers():
    """The pool, created on first use. Spawned, not forked: the servers that
    call this are threaded, and forking a threaded process is unsafe."""
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
    """Whether board() splits its solves across workers here."""
    return PARALLEL and catalog is None and (os.cpu_count() or 1) > 1


def warm():
    """Start the workers now, so the first board does not pay for it. Returns
    the number started, 0 when the board runs sequentially here."""
    if not parallel_available():
        return 0
    pool = _workers()
    futures = [pool.submit(os.getpid) for _ in range(WORKERS)]
    concurrent.futures.wait(futures)
    return WORKERS


def _seat(world, map_name, enemy, own, top, pool_size, bans, side, seat, weights=None):
    """One seat, in a worker: its optimal six against the enemy's revealed picks,
    and its own picks scored on that optimal's scale."""
    catalog = catalog_module.weighted(catalog_module.load(), weights)
    optimal = infer(world, map_name, enemy, [], top, pool_size, catalog, bans, side, seat)
    cur = current(world, optimal, map_name, enemy, own, catalog, bans, side, pool_size, seat)
    _finish(cur, optimal.score)
    return optimal, cur


def board(world, map_name=None, red=(), blue=(), bans=(), side="", pool_size=6,
          catalog=None, top=5, weights=None):
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
                     the map's pick rates and the authored synergies, past the
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
    fill = None
    if parallel:
        try:
            pool = _workers()
            seats = [pool.submit(_seat, world, map_name, enemy, list(blue), top, pool_size,
                                 list(bans), side, "blue", weights),
                     pool.submit(_seat, world, map_name, list(blue), list(red), top, pool_size,
                                 list(bans), opposite(side), "red", weights)]
            if 0 < len(blue) < TEAM_SIZE:              # the fill, here, meanwhile
                fill = infer(world, map_name, enemy, blue, top, pool_size, catalog, bans,
                             side, "blue")
            (blue_r, cur), (red_r, red_cur) = seats[0].result(), seats[1].result()
        except concurrent.futures.process.BrokenProcessPool:
            _drop_workers()                          # a worker died: this board, sequentially
            parallel = False
    if not parallel:
        blue_r = infer(world, map_name, enemy, [], top, pool_size, catalog, bans, side, "blue")
        red_r = infer(world, map_name, blue, [], top, pool_size, catalog, bans, opposite(side),
                      "red")
        cur = current(world, blue_r, map_name, enemy, blue, catalog, bans, side, pool_size)
        _finish(cur, blue_r.score)                 # 100 is blue's optimal, whatever you hold
        red_cur = current(world, red_r, map_name, blue, red, catalog, bans, opposite(side),
                          pool_size, "red")
        _finish(red_cur, red_r.score)
    countered = None
    if blue and red_r.blue:
        hypothetical = min(pool_size, 4)           # a what-if: a smaller field is enough
        against = infer(world, map_name, red_r.blue, [], top, hypothetical, catalog, bans,
                        side, "blue")
        countered = current(world, against, map_name, red_r.blue, blue, catalog, bans, side,
                            hypothetical)
        countered.kind = "countered"
        _finish(countered, against.score)
    if fill is None and 0 < len(blue) < TEAM_SIZE:
        fill = infer(world, map_name, enemy, blue, top, pool_size, catalog, bans, side, "blue")
    if fill is not None:
        fill.kind = "fill"
        _finish(fill, blue_r.score)                # how close the best completion comes
    return {"map": m.name if m else None, "side": side, "bans": list(bans),
            "blue": blue_r, "red": red_r, "current": cur, "red_current": red_cur, "fill": fill,
            "countered": countered, "momentum": _momentum(cur, red_cur, countered, blue_r, red_r),
            "plan": _plan(world, m, side, list(bans), red_h, blue_r),
            "shapes": [list(s) for s in legal_shapes(catalog)], "expected": expected}
