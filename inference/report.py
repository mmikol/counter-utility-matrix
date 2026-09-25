"""The validation's report: the records inference.validate answers - JSON
the door serves and the page draws - and the same report as text. Its
figures read Blizzard's rates where a record says rate-derived, so the
report is for the owner's own use.

    Validation     the whole run: the playbook, the pin, the digests, the maps,
                   the guard, each split, the effects and the verdict
    SplitReport    one split's models, what the playbook adds, the ablations
    MatchRow       one judged map
    rendered       a Validation as text
"""

from typing import NotRequired, TypedDict

from inference import predict, rescore
from inference.fit import Estimate


class Guard(TypedDict):
    """Whether the decided maps are enough for the effect asked about: the
    maps, the effect as a win chance and in log-odds, the maps it needs,
    the maps each reference effect needs, and the verdict's first words."""
    decided: int
    effect: float
    log_odds: float
    needed: int
    reference: dict[str, int]
    enough: bool
    text: str


class Ablation(TypedDict):
    """M4 with one family dropped: its log loss, and that minus M4's on the
    same maps - above 0, the family was carrying weight."""
    id: str
    family: str
    ids: list[str]
    log_loss: Estimate
    vs_full: Estimate


class SplitReport(TypedDict):
    """One split: its folds, the maps and sessions it scored, each model,
    M4 minus M3 (what the playbook and the matchups add to the heroes), the
    ablations, and the verdict - None while the guard holds it back."""
    name: str
    meaning: str
    folds: int
    scored: int
    sessions: int
    models: list[predict.ModelScore]
    playbook_adds: Estimate | None
    ablations: list[Ablation]
    verdict: str | None


class HeroEffect(TypedDict):
    """A hero's effect in M3 fitted on every decided map, in log-odds, and
    the maps it was on either side."""
    hero: str
    effect: float
    maps: int


class ScoreEffect(TypedDict):
    """The playbook score difference's effect in M4 fitted on every decided
    map, in log-odds per sd, and the decided maps an effect that size needs."""
    log_odds: float
    needed: int


class MatchRow(TypedDict):
    """One judged map: what was recorded, each seat's playbook score, the
    rate-derived map win difference, the matchup metrics, and the chance
    each model gave blue on each split, where the split scored it."""
    match_id: int
    played_on: str
    map: str
    side: str
    result: str
    digest: str
    note: str
    blue: list[str]
    red: list[str]
    blue_score: float
    red_score: float
    map_win_diff: float
    matchup: dict[str, float]
    predictions: dict[str, dict[str, float]]
    blue_team: NotRequired[dict[str, float]]
    red_team: NotRequired[dict[str, float]]


class FamilyRecord(TypedDict):
    """A family as the report lists it."""
    name: str
    meaning: str
    ids: list[str]


class Playbook(TypedDict):
    """The playbook judged: its folder, its digest, whether anything in it
    scores, and its families."""
    name: str
    digest: str
    scoring: bool
    families: list[FamilyRecord]


class Counts(TypedDict):
    """The maps: recorded, set aside by the pin, refused by the engine,
    judged, and of those decided, won, lost and drawn, over how many
    sessions."""
    recorded: int
    set_aside: int
    refused: int
    judged: int
    decided: int
    won: int
    lost: int
    drawn: int
    sessions: int


class RefusedRecord(TypedDict):
    """A map the engine refused, and why."""
    match_id: int
    reason: str


class Validation(TypedDict):
    """The whole run, JSON-ready: the playbook, whether the pin held, the
    digests, the counts, the refused maps, the guard, each split, the hero
    and score effects fitted on every decided map, each judged map, and the
    verdict in words."""
    playbook: Playbook
    pinned: bool
    pins: list[rescore.Pin]
    counts: Counts
    refused: list[RefusedRecord]
    guard: Guard
    splits: list[SplitReport]
    heroes: list[HeroEffect]
    score_effect: ScoreEffect | None
    matches: list[MatchRow]
    verdict: str


# --- the text -------------------------------------------------------------------

def _interval(e: Estimate) -> str:
    return "%.3f [%.3f, %.3f]" % (e["value"], e["low"], e["high"])


def _signed(e: Estimate) -> str:
    return "%+.3f [%+.3f, %+.3f]" % (e["value"], e["low"], e["high"])


def _head(v: Validation) -> list[str]:
    """The playbook, the maps it is judged on, the pin and the guard."""
    c, book = v["counts"], v["playbook"]
    pin = "  unpinned: every map judged, the ones the playbook was tuned on included"
    if v["pinned"]:
        pin = "  pinned: %d earlier maps set aside - the playbook may have been tuned on them" % (
            c["set_aside"])
    return [
        "validation of %s (digest %s): %d recorded maps, %d judged%s" % (
            book["name"], book["digest"][:12], c["recorded"], c["judged"],
            "" if book["scoring"] else "; the playbook scores nothing, so every map reads 0"),
        pin,
        "  decided %d (%d won, %d lost), %d drawn, over %d sessions%s" % (
            c["decided"], c["won"], c["lost"], c["drawn"], c["sessions"],
            "; %d refused by the engine" % c["refused"] if c["refused"] else ""),
        *["  refused %d: %s" % (r["match_id"], r["reason"]) for r in v["refused"]],
        "  guard: " + v["guard"]["text"]]


def _split_lines(split: SplitReport) -> list[str]:
    """One split: its folds, each model's scores, M4 against M3 and the
    ablations."""
    lines = ["%s split - %s: %d folds, %d maps over %d sessions scored" % (
        split["name"], split["meaning"], split["folds"], split["scored"], split["sessions"])]
    lines += ["  %-3s log loss %s  Brier %s  vs coin %s  %s" % (
        m["id"], _interval(m["log_loss"]), _interval(m["brier"]), _signed(m["vs_coin"]),
        m["label"]) for m in split["models"]]
    if split["playbook_adds"] is not None:
        lines.append("  M4 - M3 log loss %s" % _signed(split["playbook_adds"]))
    lines += ["  without %-9s %s vs M4 (%s)" % (
        a["family"], _signed(a["vs_full"]), ", ".join(a["ids"])) for a in split["ablations"]]
    return lines


def _digest(p: rescore.Pin) -> str:
    """One digest: its maps and dates, and whether it is the one judged."""
    return "%s %d maps %s..%s%s" % (p["digest"][:12], p["maps"], p["first"], p["last"],
                                    " (judged)" if p["judged"] else "")


def _tail(v: Validation) -> list[str]:
    """The effects fitted on every decided map, the digests and the verdict."""
    lines = []
    effect = v["score_effect"]
    if effect is not None:
        lines.append("playbook score difference on every decided map: %+.3f log-odds per sd,"
                     " an effect that size needs %d maps" % (effect["log_odds"], effect["needed"]))
    heroes = v["heroes"]
    if heroes:
        ends = heroes[:3] + heroes[-3:] if len(heroes) > 6 else heroes
        lines.append("hero effects on every decided map (M3, log-odds): %s" % ", ".join(
            "%s %+.2f" % (h["hero"], h["effect"]) for h in ends))
    digests = "; ".join(_digest(p) for p in v["pins"]) or "none recorded"
    lines.append("digests: %s" % digests)
    lines.append("verdict: " + v["verdict"])
    return lines


def rendered(v: Validation) -> str:
    """The validation as text: the playbook and the maps, the pin, the
    guard, each split's models and ablations, the effects and the verdict."""
    lines = _head(v)
    for split in v["splits"]:
        lines += _split_lines(split)
    return "\n".join(lines + _tail(v))
