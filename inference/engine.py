"""infer(), evaluate() and board(): the solver plus the facts it cites.

    infer(world, "King's Row", red=["Zarya", "Pharah"], blue=["Ana"], side="attack")

returns the optimal six around the locked picks, each pick with the facts
that justify it (the board the UI layer would show for map + red + the
six), the score broken down per strategy, and the alternatives.
board() does it for both seats - blue around its locked picks, red around
its revealed ones, on opposite sides of a sided map - and scores the
current blue picks as they stand.
"""

import time

from ui.core import engine as facts_engine
from ui.core.compute import TEAM_SIZE, is_sided, opposite
from inference import catalog as catalog_module
from inference.solver import Candidate, Solver, evaluate_comp

ROLE_ORDER = {"tank": 0, "damage": 1, "support": 2}


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
        # the prose constraints - no score to add: what the agent reconciles the
        # facts against beyond the arithmetic
        self.considerations = [{"id": h.id, "name": h.name}
                               for h in catalog if h.form == "prose"]

    def to_dict(self, include_facts=False):
        counts = {k: sum(1 for h in self.catalog if h.kind == k)
                  for k in catalog_module.KINDS}
        cited = {}
        if self.facts is not None:
            ids = {fid for p in self.picks for fid in p["evidence"]}
            ids |= {c["fact"] for c in self.contributions if c.get("fact")}
            cited = {f.id: f.text for f in self.facts.facts if f.id in ids}
        return {"kind": self.kind, "seat": self.seat, "map": self.map_name,
                "red": self.red, "blue": self.blue, "locked": self.locked,
                "bans": self.bans, "side": self.side, "partial": self.partial,
                "score": round(self.score, 3),
                "playstyle": self.playstyle, "picks": self.picks,
                "contributions": self.contributions, "violations": self.violations,
                "alternatives": self.alternatives, "rank": self.rank,
                "considered": self.considered, "seconds": round(self.seconds, 2),
                "strategies": counts, "cited": cited,
                "considerations": self.considerations,
                "facts": self.facts.to_dict() if (include_facts and self.facts) else None}

    def rendered(self):
        head = "%s for %s%s%s vs %s%s%s" % (
            {"infer": "optimal comp", "evaluate": "evaluation",
             "current": "current comp"}[self.kind],
            "red" if self.seat == "red" else "blue",
            " on %s" % self.side if self.side else "",
            " on %s" % self.map_name if self.map_name else "",
            ", ".join(self.red) or "an unknown enemy",
            " (locked: %s)" % ", ".join(self.locked) if self.locked else "",
            " (banned: %s)" % ", ".join(self.bans) if self.bans else "")
        counts = {k: sum(1 for h in self.catalog if h.kind == k)
                  for k in catalog_module.KINDS}
        lines = [head, "  %s%s - score %.2f%s, %d candidates considered in %.1fs"
                 " under %d constraints and %d heuristics"
                 % (", ".join(self.blue), " (%s)" % self.playstyle if self.playstyle else "",
                    self.score, " (rank %d among the feasible field)" % self.rank
                    if self.rank else "", self.considered, self.seconds,
                    counts["constraint"], counts["heuristic"])]
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
        return "\n".join(lines)


def _reasons(fs, hero_name, locked):
    """The facts that justify one pick, from the board's own FactSet."""
    why, evidence = [], []

    def cite(key, template):
        for f in fs.find(key, hero_name):
            why.append(template(f))
            evidence.append(f.id)
            return True
        return False

    cite("hero.vs_answers", lambda f: "answers %s" % ", ".join(f.value))
    partners = fs.find("hero.with_ally", hero_name)
    if partners:
        why.append("partner of %s" % ", ".join(f.value for f in partners[:3]))
        evidence.extend(f.id for f in partners[:3])
    cite("hero.map_win", lambda f: "wins %.1f%% here" % f.value)
    for f in fs.find("hero.map_delta", hero_name):
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
    return result


def current(world, blue_result, map_name=None, red=(), blue=(), catalog=None, bans=(),
            side="", pool_size=6):
    """The current blue picks as they stand: a full six is evaluated against
    the field; a partial team is scored with the bounds of the optimal
    search it came from, and says so."""
    if len(blue) == TEAM_SIZE:
        return evaluate(world, map_name, red, blue, pool_size, catalog, bans, side)
    started = time.time()
    m, red_h, blue_h, bans_h = world.resolve(map_name, red, blue, bans)
    side = _side(m, side)
    result = Result("current", m.name if m else None, [h.name for h in red_h],
                    [h.name for h in blue_h], [h.name for h in blue_h], catalog,
                    [h.name for h in bans_h], side)
    result.partial = True
    if not blue_h:
        result.seconds = time.time() - started
        return result
    solver = blue_result.solver
    cand = solver.prepare(Candidate(blue_h))
    solver.score(cand)
    fs = facts_engine.generate(world, result.map_name, result.red, result.blue, result.bans,
                               side)
    _fill(result, cand, fs, solver)
    result.seconds = time.time() - started
    return result


def board_dict(b):
    """The board() result as JSON-ready data."""
    return {"map": b["map"], "side": b["side"], "bans": b["bans"],
            "blue": b["blue"].to_dict(), "red": b["red"].to_dict(),
            "current": b["current"].to_dict()}


def board_rendered(b):
    return "\n\n".join(r.rendered() for r in (b["blue"], b["red"], b["current"])
                       if r.blue or r.kind != "current")


def board(world, map_name=None, red=(), blue=(), bans=(), side="", pool_size=6,
          catalog=None, top=5):
    """Both seats and the current comp in one pass:

        blue     the optimal six around blue's locked picks, on `side`
        red      the optimal six around red's revealed picks, on the other side
        current  blue's picks as they stand (full: ranked; partial: scored)
    """
    catalog = catalog or catalog_module.load()
    m, _, _, _ = world.resolve(map_name, red, blue, bans)
    side = _side(m, side)
    blue_r = infer(world, map_name, red, blue, top, pool_size, catalog, bans, side, "blue")
    red_r = infer(world, map_name, blue, red, top, pool_size, catalog, bans,
                  opposite(side), "red")
    cur = current(world, blue_r, map_name, red, blue, catalog, bans, side, pool_size)
    return {"map": m.name if m else None, "side": side, "bans": list(bans),
            "blue": blue_r, "red": red_r, "current": cur}
