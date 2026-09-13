"""Fitting the goal weights to recorded outcomes.

For every recorded match with both sixes known, compute each goal's metric
for blue against red on that map and side, normalise it across the
outcomes (0..1, flipped for minimise), and ask: did this metric run higher
in wins than in losses? That difference, in [-1, 1], is the evidence for
the goal. A proposal nudges each weight by RATE x evidence, bounded, and
only when at least MIN_OUTCOMES decided matches exist - with a handful of
games the honest answer is "not yet".

    propose(cx)            -> the proposal, nothing written
    apply(cx, proposal)    -> each nudge applied through inference.tune,
                              logged with the sample size

This is a bounded, explainable update, not a learner: it moves weights
toward what has been separating wins from losses in your own games, one
small step per fit, and every step is a line in the tuning log.
"""

from user.facts import compute, model
from inference import catalog as catalog_module
from inference import tune as tune_module
from inference.expr import lookup

MIN_OUTCOMES = 10
RATE = 0.5           # weight moves by up to RATE x evidence per fit
MIN_WEIGHT, MAX_WEIGHT = 0.25, 6.0


def _scored_outcomes(world):
    """[(result, namespace)] for every decided outcome with both sixes."""
    out = []
    for o in world.outcomes:
        if o["result"] not in ("win", "loss"):
            continue
        blue = [world.heroes[h] for h in o["blue"] if h in world.heroes]
        red = [world.heroes[h] for h in o["red"] if h in world.heroes]
        if len(blue) != compute.TEAM_SIZE or len(red) != compute.TEAM_SIZE:
            continue
        m = world.maps.get(o["map_id"])
        out.append((o["result"], compute.namespace(world, m, red, blue, o["side"] or "")))
    return out


def propose(cx, catalog=None, min_outcomes=MIN_OUTCOMES, rate=RATE):
    catalog = catalog or catalog_module.load()
    world = model.load(cx)
    scored = _scored_outcomes(world)
    wins = sum(1 for r, _ in scored if r == "win")
    losses = len(scored) - wins
    proposal = {"outcomes": len(scored), "wins": wins, "losses": losses,
                "min_outcomes": min_outcomes, "ready": len(scored) >= min_outcomes
                and wins and losses, "goals": []}
    for g in (h for h in catalog if h.kind == "goal"):
        values = [(r, float(lookup(ns, g.metric) or 0)) for r, ns in scored]
        if not values:
            continue
        lo, hi = min(v for _, v in values), max(v for _, v in values)
        if hi > lo:
            norms = [(r, (v - lo) / (hi - lo)) for r, v in values]
        else:
            norms = [(r, 0.5) for r, _ in values]
        if g.direction == "minimize":
            norms = [(r, 1.0 - n) for r, n in norms]
        win_mean = sum(n for r, n in norms if r == "win") / max(wins, 1)
        loss_mean = sum(n for r, n in norms if r == "loss") / max(losses, 1)
        evidence = win_mean - loss_mean if wins and losses else 0.0
        new = g.weight * (1.0 + rate * evidence)
        new = round(min(MAX_WEIGHT, max(MIN_WEIGHT, new)), 2)
        proposal["goals"].append({
            "id": g.id, "metric": g.metric, "weight": g.weight, "proposed": new,
            "evidence": round(evidence, 3), "win_mean": round(win_mean, 3),
            "loss_mean": round(loss_mean, 3),
            "change": round(new - g.weight, 2) if proposal["ready"] else 0.0})
    proposal["goals"].sort(key=lambda x: -abs(x["evidence"]))
    return proposal


def apply(cx, proposal, by="fit", directory=None):
    """Write every non-zero nudge through tune(); returns the tune records."""
    if not proposal["ready"]:
        raise ValueError("not enough decided outcomes to fit: %d of %d needed"
                         " (with at least one win and one loss)"
                         % (proposal["outcomes"], proposal["min_outcomes"]))
    applied = []
    for g in proposal["goals"]:
        if abs(g["change"]) < 0.005:
            continue
        applied.append(tune_module.tune(
            g["id"], "weight", g["proposed"],
            "fit from %d outcomes (%d-%d): %s ran %s in wins (evidence %+.2f)"
            % (proposal["outcomes"], proposal["wins"], proposal["losses"], g["metric"],
               "higher" if g["evidence"] > 0 else "lower", g["evidence"]),
            directory=directory, by=by))
    return applied


def rendered(proposal):
    head = "fit: %d decided outcomes (%d wins, %d losses); %s" % (
        proposal["outcomes"], proposal["wins"], proposal["losses"],
        "ready to apply" if proposal["ready"]
        else "needs %d before weights move" % proposal["min_outcomes"])
    lines = [head]
    for g in proposal["goals"]:
        lines.append("  %-22s evidence %+.2f (wins %.2f, losses %.2f)  weight %g -> %g"
                     % (g["id"], g["evidence"], g["win_mean"], g["loss_mean"],
                        g["weight"], g["proposed"]))
    return "\n".join(lines)
