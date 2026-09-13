"""Fitting the goal weights to recorded outcomes.

For every recorded match with both sixes known, score blue's six against
red on that map and side the way the solver would - each goal's metric,
normalised against the solver's own reference sample for that board
(0..1, flipped for minimise) - and ask which goals ran higher in wins than
in losses. Two tiers of evidence, in [-1, 1] per goal:

    mean difference   from MIN_OUTCOMES (10) decided matches: the mean
                      normalised value in wins minus that in losses
    logistic          from LOGISTIC_MIN (50): a ridge logistic regression
                      of win/loss on the goals' values, each demeaned
                      within its map so a map that is simply won more
                      often does not masquerade as a metric; the evidence
                      is tanh of the coefficient

A proposal nudges each weight by RATE x evidence, bounded; below the
minimum the honest answer is "not yet".

    propose(cx)            -> the proposal, nothing written
    apply(cx, proposal)    -> each nudge applied through inference.tune,
                              logged with the sample size

This is a bounded, explainable update, not a learner: it moves weights
toward what has been separating wins from losses in your own games, one
small step per fit, and every step is a line in the tuning log.
"""

import math

from user.facts import compute, model
from inference import catalog as catalog_module
from inference import tune as tune_module
from inference.solver import Candidate, Solver

MIN_OUTCOMES = 10
LOGISTIC_MIN = 50
RATE = 0.5           # weight moves by up to RATE x evidence per fit
MIN_WEIGHT, MAX_WEIGHT = 0.25, 6.0
REFERENCE_SIZE = 600


def _scored_outcomes(world, catalog):
    """[(result, map_id, {goal id: normalised value})] for every decided
    outcome with both sixes, on the solver's scale for that board."""
    goals = [h for h in catalog if h.kind == "goal"]
    out = []
    for o in world.outcomes:
        if o["result"] not in ("win", "loss"):
            continue
        blue = [world.heroes[h] for h in o["blue"] if h in world.heroes]
        red = [world.heroes[h] for h in o["red"] if h in world.heroes]
        if len(blue) != compute.TEAM_SIZE or len(red) != compute.TEAM_SIZE:
            continue
        m = world.maps.get(o["map_id"])
        bans = [world.heroes[h] for h in o["bans"] if h in world.heroes]
        solver = Solver(world, m, red, [], catalog, 6, bans, o["side"] or "")
        solver.reference(REFERENCE_SIZE)
        solver.freeze_bounds()
        cand = solver.prepare(Candidate(blue))
        norms = {}
        for g in goals:
            raw = cand.raw.get(g.id)
            lo, hi = solver.bounds.get(g.id, (0.0, 0.0))
            if raw is None:
                continue
            n = (raw - lo) / (hi - lo) if hi > lo else 0.5
            n = min(1.0, max(0.0, n))
            norms[g.id] = 1.0 - n if g.direction == "minimize" else n
        out.append((o["result"], o["map_id"], norms))
    return out


def mean_difference(scored, goal_id):
    wins = [n[goal_id] for r, _, n in scored if r == "win" and goal_id in n]
    losses = [n[goal_id] for r, _, n in scored if r == "loss" and goal_id in n]
    if not wins or not losses:
        return 0.0, 0.0, 0.0
    w, l = sum(wins) / len(wins), sum(losses) / len(losses)
    return w - l, w, l


def logistic_evidence(scored, goal_ids, l2=1.0, steps=400, lr=0.05):
    """{goal id: tanh(coefficient)} from a ridge logistic regression of the
    result on the goals' normalised values, standardised and demeaned
    within each map. Pure Python gradient descent - the samples are dozens,
    not millions."""
    rows = [(1.0 if r == "win" else 0.0, mid, n) for r, mid, n in scored]
    if not rows:
        return {}
    ids = [g for g in goal_ids if all(g in n for _, _, n in rows)]
    # demean within map, then standardise each feature
    by_map = {}
    for _, mid, n in rows:
        by_map.setdefault(mid, []).append(n)
    map_mean = {mid: {g: sum(n[g] for n in ns) / len(ns) for g in ids}
                for mid, ns in by_map.items()}
    X = [[n[g] - map_mean[mid][g] for g in ids] for _, mid, n in rows]
    y = [r for r, _, _ in rows]
    cols = list(zip(*X)) if X else []
    scale = []
    for j, col in enumerate(cols):
        mean = sum(col) / len(col)
        sd = math.sqrt(sum((v - mean) ** 2 for v in col) / max(len(col) - 1, 1)) or 1.0
        scale.append((mean, sd))
        for i in range(len(X)):
            X[i][j] = (X[i][j] - mean) / sd
    k = len(ids)
    w, b = [0.0] * k, 0.0
    n = float(len(X))
    for _ in range(steps):
        grad_w, grad_b = [0.0] * k, 0.0
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            err = p - yi
            grad_b += err
            for j in range(k):
                grad_w[j] += err * xi[j]
        b -= lr * grad_b / n
        for j in range(k):
            w[j] -= lr * (grad_w[j] / n + l2 * w[j] / n)
    return {g: math.tanh(w[j]) for j, g in enumerate(ids)}


def propose(cx, catalog=None, min_outcomes=MIN_OUTCOMES, rate=RATE,
            logistic_min=LOGISTIC_MIN):
    catalog = catalog or catalog_module.load()
    world = model.load(cx)
    scored = _scored_outcomes(world, catalog)
    wins = sum(1 for r, _, _ in scored if r == "win")
    losses = len(scored) - wins
    ready = len(scored) >= min_outcomes and wins > 0 and losses > 0
    goals = [h for h in catalog if h.kind == "goal"]
    logistic = (logistic_evidence(scored, [g.id for g in goals])
                if ready and len(scored) >= logistic_min else {})
    proposal = {"outcomes": len(scored), "wins": wins, "losses": losses,
                "min_outcomes": min_outcomes, "ready": ready,
                "method": ("logistic, demeaned within map" if logistic
                           else "mean difference"), "goals": []}
    for g in goals:
        diff, win_mean, loss_mean = mean_difference(scored, g.id)
        evidence = logistic.get(g.id, diff) if ready else 0.0
        new = g.weight * (1.0 + rate * evidence)
        new = round(min(MAX_WEIGHT, max(MIN_WEIGHT, new)), 2)
        proposal["goals"].append({
            "id": g.id, "metric": g.metric, "weight": g.weight, "proposed": new,
            "evidence": round(evidence, 3), "win_mean": round(win_mean, 3),
            "loss_mean": round(loss_mean, 3),
            "change": round(new - g.weight, 2) if ready else 0.0})
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
    head = "fit: %d decided outcomes (%d wins, %d losses); %s%s" % (
        proposal["outcomes"], proposal["wins"], proposal["losses"],
        "ready to apply" if proposal["ready"]
        else "needs %d before weights move" % proposal["min_outcomes"],
        " - %s" % proposal["method"] if proposal["ready"] else "")
    lines = [head]
    for g in proposal["goals"]:
        lines.append("  %-22s evidence %+.2f (wins %.2f, losses %.2f)  weight %g -> %g"
                     % (g["id"], g["evidence"], g["win_mean"], g["loss_mean"],
                        g["weight"], g["proposed"]))
    return "\n".join(lines)
