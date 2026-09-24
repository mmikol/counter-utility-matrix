"""The Result and Board records and the facts they cite.

A Result is one seat's six on one board: who is in it and why, each pick
citing the board facts that justify it, the score and its breakdown per
strategy, and the runners-up. A Board holds the seven Results board()
solves, with the verdict and the plan read off them. Both render as
JSON-ready data (to_dict) and as text (rendered).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, NotRequired, TypedDict

from inference import catalog as catalog_module
from inference.catalog import Strategy
from inference.scoring import Candidate, Contribution
from ui.facts.draft import TEAM_SIZE
from ui.facts.factset import Fact, FactSet
from ui.facts.model import ROLES
from ui.facts.team import text

# A result or a board as to_dict() serves it: JSON, read by the shells.
Payload = dict[str, Any]


class Pick(TypedDict):
    """One hero of a result's six, with the reason it is there and the ids of
    the facts the reason cites. A solved six carries each hero's subrole and
    portrait; red's likely six carries the pick rate it rests on instead."""
    hero: str
    role: str
    locked: bool
    why: str
    evidence: list[str]
    subrole: NotRequired[str]
    portrait: NotRequired[str | None]
    rate: NotRequired[float | None]


class Alternative(TypedDict):
    """A runner-up six: its heroes, its score, and its share of the result's
    best - None until the result is scaled, and where it reads unscored."""
    blue: list[str]
    score: float
    normalized: int | None


class Consideration(TypedDict):
    """An assumption of the playbook: prose a comp is reconciled against."""
    id: str
    name: str


class Odds(TypedDict):
    """The two shares pitted against each other: each seat's part of 100."""
    blue: int
    red: int


class Momentum(TypedDict):
    """Who the picks favour: each seat's share of its optimal, blue's share
    against red's best counter, whether either seat is half-drafted, the
    fight odds and the verdict in words. A share is None where it cannot be
    read."""
    blue: int | None
    red: int | None
    countered: int | None
    partial: bool
    odds: Odds | None
    verdict: str


def _pct(score: float, best: float) -> int:
    """A score as a share of the board's best, 0-100: the optimal six is 100,
    the current comp its percentage of blue's optimal, an alternative its
    share of the winner. A best at or below zero makes the scale meaningless,
    so only the best itself scores 100 there."""
    if best <= 0:
        return 100 if score >= best else 0
    return max(0, min(100, round(100.0 * score / best)))


# what each kind of result is, as its rendered heading names it
HEADINGS = {"infer": "optimal comp", "evaluate": "evaluation", "current": "current comp",
            "countered": "if countered optimally", "fill": "your picks, the rest filled",
            "expected": "their likely starting comp"}
UNSCORED = ("unscored - the playbook in force holds no heuristic, scored constraint or soft"
            " limit, so every legal six ties at zero; add one and the board scores")


@dataclass(kw_only=True, eq=False)
class Result:
    """One seat's six on one board: who is in it and why, what it scores and
    how that breaks down per strategy, the runners-up, and the facts it
    cites. Built empty around the board's names; record_candidate() writes
    the six onto it and scale_to() sets what 100 means."""
    kind: str
    map_name: str | None
    red: list[str]
    blue: list[str]
    locked: list[str]
    catalog: list[Strategy]
    bans: list[str] = field(default_factory=list)
    side: str = ""
    seat: str = "blue"
    partial: bool = False
    score: float = 0.0
    picks: list[Pick] = field(default_factory=list)
    contributions: list[Contribution] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    alternatives: list[Alternative] = field(default_factory=list)
    facts: FactSet | None = None
    considered: int = 0
    seconds: float = 0.0
    rank: int | None = None
    playstyle: str = ""
    best: float | None = None          # the board's best score: what 100 means here
    # the assumptions - nothing to score: what the agent reconciles the facts
    # against beyond the arithmetic
    considerations: list[Consideration] = field(init=False)
    # drafts: name, kind and prose only - shown, not scored, until /strategy
    pending: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.considerations = [Consideration(id=h.id, name=h.name)
                               for h in self.catalog if h.kind == "assumption"]
        self.pending = [h.id for h in self.catalog if h.pending]

    def scale_to(self, best: float) -> None:
        """Set what 100 means here - the board's best score - and write each
        alternative's share of it, None while the result reads unscored."""
        self.best = best
        scoring = self.unscored() is None
        for alt in self.alternatives:
            alt["normalized"] = _pct(alt["score"], best) if scoring else None

    def share(self) -> int:
        """The score as a share of what 100 means here, 0-100."""
        return _pct(self.score, self._hundred())

    def _hundred(self) -> float:
        """What 100 means for the result: the board's best score, else its own."""
        return self.best if self.best is not None else self.score

    def unscored(self) -> str | None:
        """Why the result carries no share of a best, or None when it does.
        The optimal six is 100 by definition - it is the reference, and scored
        always; any other comp reads unscored when nothing can be a share of
        anything: the playbook holds no term that scores, or none of its terms
        applies to this board (a heuristic waiting on its `when`), so the best
        six itself sums to zero."""
        if self.kind == "infer":
            return None
        return self.waiting()

    def waiting(self) -> str | None:
        """The reason nothing on this board scores, or None: read off any
        result, the optimal included (a seat with no picks has no comp to read
        it from)."""
        if not catalog_module.has_scoring_terms(self.catalog):
            return UNSCORED
        best = self._hundred()
        if best > 0:
            return None
        by_id = {h.id: h for h in self.catalog}
        waiting = []
        for c in self.contributions:
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

    def record_candidate(self, cand: Candidate, fs: FactSet, considered: int) -> None:
        """Write a scored candidate onto the result: its score, breakdown and
        breaches, the board's facts, how many sixes the search considered, the
        six's lean, and a pick per hero with the facts that justify it. Each
        contribution cites the board fact that states its metric."""
        if cand.ns is None:
            raise RuntimeError("record_candidate() takes a scored candidate: hydrate() a slim one")
        self.score = cand.score
        self.contributions = cand.contributions
        self.violations = cand.violations
        self.facts = fs
        self.considered = considered
        team = cand.ns["team"]
        self.playstyle = text(team["style_lean"]) or text(team["style_top"])
        locked = set(self.locked)
        for h in sorted(cand.heroes, key=lambda h: (ROLES.index(h.role), h.name)):
            why, evidence = _reasons(fs, h.name, h.name in locked)
            self.picks.append(Pick(hero=h.name, role=h.role, subrole=h.subrole,
                                   portrait=h.portrait, locked=h.name in locked, why=why,
                                   evidence=evidence))
        by_id = {h.id: h for h in self.catalog}
        for c in self.contributions:
            fact = _cited_fact(fs, _metric_keys(by_id.get(c["id"])))
            if fact is not None:
                c["fact"], c["text"] = fact.id, fact.text

    def to_dict(self) -> Payload:
        """The result as JSON-ready data. The facts it cites ride along as
        `cited`, id to text; the board's whole FactSet is the facts route's."""
        cited = {}
        if self.facts is not None:
            ids = {fid for p in self.picks for fid in p["evidence"]}
            ids |= {c["fact"] for c in self.contributions if c.get("fact")}
            cited = {f.id: f.text for f in self.facts.facts if f.id in ids}
        unscored = self.unscored()
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
                "normalized": self.share() if scoring and not self.partial else None,
                "playstyle": self.playstyle, "picks": self.picks,
                "contributions": self.contributions, "violations": self.violations,
                "alternatives": self.alternatives, "rank": self.rank,
                "considered": self.considered, "seconds": round(self.seconds, 2),
                "strategies": catalog_module.counts(self.catalog), "cited": cited,
                "considerations": self.considerations, "pending": self.pending}

    def rendered(self) -> str:
        """The result as text: the heading, the six and its score, and a line
        each for the picks, the breakdown and the alternatives."""
        counts = catalog_module.counts(self.catalog)
        unscored = self.unscored()
        lines = [self._headline(), "  %s%s - score %.2f %s%s, %d candidates considered in %.1fs"
                 " under %d constraints, %d heuristics and %d assumptions"
                 % (", ".join(self.blue), " (%s)" % self.playstyle if self.playstyle else "",
                    self.score, self._share_label(unscored),
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
        lines += ["  %-8s %-14s %s" % (p["role"], p["hero"] + ("*" if p["locked"] else ""),
                                       p["why"])
                  for p in self.picks]
        lines.append(self._breakdown())
        lines += ["  alt %d: %s (%.2f)" % (i, ", ".join(alt["blue"]), alt["score"])
                  for i, alt in enumerate(self.alternatives, start=1)]
        if self.considerations:
            lines.append("  ground rules to reconcile against: " + ", ".join(
                c["id"] for c in self.considerations))
        if self.pending:
            lines.append("  drafts not yet scored (run /strategy): " + ", ".join(self.pending))
        return "\n".join(lines)

    def _headline(self) -> str:
        """What the result is, for which seat, where and against whom."""
        return "%s for %s%s%s vs %s%s%s" % (
            HEADINGS[self.kind],
            "red" if self.seat == "red" else "blue",
            " on %s" % self.side if self.side else "",
            " on %s" % self.map_name if self.map_name else "",
            ", ".join(self.red) or "an unknown enemy",
            " (locked: %s)" % ", ".join(self.locked) if self.locked else "",
            " (banned: %s)" % ", ".join(self.bans) if self.bans else "")

    def _share_label(self, unscored: str | None) -> str:
        """The score's share of the best, or why there is none."""
        if self.kind == "expected":                # a likelihood, not a score
            return "(from the map's pick rates and the synergies, no strategy read)"
        if unscored is not None:
            return "(unscored)"
        if self.partial:
            return "(partial - see the filled six for a share)"
        return "(%d/100)" % self.share()

    def _breakdown(self) -> str:
        """Each applying term's weighted part of the score, a need marked."""
        parts = ["%s %+.2f%s" % (c["id"], c["weighted"], " (need)" if c.get("need") else "")
                 for c in self.contributions
                 if c["applies"] and abs(c["weighted"]) >= 0.005]
        return "  breakdown: " + " · ".join(parts)


@dataclass(kw_only=True, eq=False)
class Board:
    """Both seats of one draft: the seven Results board() solves, the verdict
    and prose it reads off them, and the shape limits the roster enforces.
    Carries the same to_dict()/rendered() pair as Result, so the shells hand a
    board to the caller the way they hand a single seat."""
    map_name: str | None
    side: str
    bans: list[str]
    blue: Result
    red: Result
    current: Result
    red_current: Result
    fill: Result | None
    countered: Result | None
    momentum: Momentum
    plan: str
    shapes: list[list[int]]
    expected: Result

    def to_dict(self) -> Payload:
        """The board as JSON-ready data."""
        return {"map": self.map_name, "side": self.side, "bans": self.bans, "plan": self.plan,
                "blue": self.blue.to_dict(), "red": self.red.to_dict(),
                "current": self.current.to_dict(), "red_current": self.red_current.to_dict(),
                "countered": self.countered.to_dict() if self.countered else None,
                "fill": self.fill.to_dict() if self.fill else None, "momentum": self.momentum,
                "shapes": self.shapes,
                "expected": self.expected.to_dict()}

    def rendered(self) -> str:
        """The board as text: the plan, each seat, and the verdict."""
        parts = ["game plan:\n" + self.plan]
        parts += [r.rendered() for r in (self.blue, self.red, self.current, self.red_current)
                  if r.blue or r.kind != "current"]
        if self.fill:
            parts.append(self.fill.rendered())
        if self.countered:
            parts.append(self.countered.rendered())
        parts.append(self.expected.rendered())
        return "\n\n".join([*parts, "momentum: " + self.momentum["verdict"]])


def rates_queue(fs: FactSet) -> str:
    """The queue the board's rates were captured in, as the game names it
    ("Role Queue"), read off the rates' meta.snapshot fact; empty where the
    board holds none. The source publishes no Open Queue rates, so a pick's
    win rate says which queue it is."""
    for f in fs.find("meta.snapshot"):
        queue = str(f.value.get("queue") or "")
        if queue:
            return queue.removeprefix("competitive_").replace("_", " ").title()
    return ""


def _reasons(fs: FactSet, hero_name: str, locked: bool) -> tuple[str, list[str]]:
    """The facts that justify one pick, from the board's own FactSet - the
    facts about OUR copy of the hero: a mirror pick has facts on both sides
    (red's Tracer answers our Ana; ours partners our D.Va), and only the
    facts the FactSet filed under the seat's own side (its "blue") count. A
    win rate names the queue it was captured in."""
    why: list[str] = []
    evidence: list[str] = []
    queue = rates_queue(fs)
    rated = ", %s" % queue if queue else ""

    def own(key: str) -> list[Fact]:
        return [f for f in fs.find(key, hero_name) if f.team in (None, "blue")]

    def cite(key: str, template: Callable[[Fact], str]) -> bool:
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
    cite("hero.map_win", lambda f: "wins %.1f%% here%s" % (f.value, rated))
    for f in own("hero.map_delta"):
        if f.value >= 2.5:
            why.append("map specialist (%+.1f)" % f.value)
            evidence.append(f.id)
    cite("hero.map_style_fit", lambda f: "fits the %s style" % f.value)
    cite("hero.map_strategy", lambda f: "top-%d map by rate" % f.value)
    cite("hero.vs_answered_by", lambda f: "CAUTION: answered by %s" % ", ".join(f.value))
    if not evidence:
        cite("hero.rate", lambda f: "wins %.1f%% across all ranks%s" % (f.value["win"], rated))
    if locked:
        why.insert(0, "locked")
    return "; ".join(why), evidence


def _metric_keys(strategy: Strategy | None) -> list[str]:
    """The metrics a contribution's fact can state: a heuristic's own, then
    every team and matchup key its expressions read."""
    if strategy is None:
        return []
    keys = [strategy.metric] if strategy.kind == "heuristic" and strategy.metric else []
    for e in (strategy.require, strategy.bonus, strategy.penalty, strategy.when):
        if e is not None:
            keys += [n for n in e.names if n.startswith(("team.", "matchup."))]
    return keys


def _cited_fact(fs: FactSet, keys: Iterable[str]) -> Fact | None:
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
