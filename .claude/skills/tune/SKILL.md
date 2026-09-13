---
name: tune
description: Change how overwatch-db's inference engine scores compositions - a heuristic's weight, a params dial, or an expression - or fit the goal weights to recorded match outcomes. Use when the user says the solver over- or under-values something, wants a rule changed, asks to "tune", "reweight", "adjust", or wants the engine to learn from their games.
---

You are editing the brain: the markdown heuristics in `inference/heuristics/`
(constraints, goals, strategies). Every change goes through the `tune`
tool on the `overwatch-db` (or `overwatch-db-docker`) MCP server, which
validates it against the catalog, writes the file, re-mirrors the table,
and logs it with your reason in `inference/tuning-log.md`. Nothing is
edited by hand.

## A manual tune ("it keeps ignoring anti-heal")

1. Read the catalog: the `heuristics` tool lists every heuristic with its
   kind, metric, direction, weight, expressions and params. Find the one
   the user means (`anti-heal-answer`, a strategy with `bonus: min(team.antiheal, 1) * 1.5`).
2. Decide the smallest change that does what they asked: a weight (goals
   and scored strategies; keep it within 0.25..5 unless they insist), a
   `params.NAME` dial, or an expression (the vocabulary is every `team.*`,
   `enemy.*`, `matchup.*`, `map.*`, `world.*` key in docs/heuristics.md).
3. Call `tune`: `{"id": "anti-heal-answer", "field": "weight", "value": 2.5,
   "reason": "user: the solver keeps ignoring anti-heal against double
   support"}`. A metric that does not exist or an expression that does not
   parse is refused; nothing changes.
4. Show the effect: re-run `board` (or `infer`) for the board the user is
   looking at and say what moved. One change per request unless they ask
   for more; never touch a heuristic they did not name.

## Fitting from outcomes ("learn from our games")

1. `fit_weights` with no arguments is a dry run: for every decided outcome
   with both sixes recorded, how each goal's metric ran in wins versus
   losses, and the bounded nudge it implies. Below the minimum sample (10
   decided matches, at least one win and one loss) it says "not yet" - tell
   the user how many more outcomes it needs (`/outcome` records them).
2. Show the proposal and ask before applying. `fit_weights` with
   `apply: true` writes every nudge through `tune`, each logged with the
   sample size and the evidence. The step is bounded (up to half the
   evidence, weights clamped to 0.25..6) so one bad week cannot flip the
   engine; run it again after more games.
3. `tuning_log` (tool) or the `heuristic://tuning-log` resource is the audit
   trail - show it when the user asks how the weights got here.

## Ground rules

- Players are assumed to play optimally; do not add a heuristic to
  encode a lobby's habits - record outcomes and let the fit speak.
- A weight of 0 silences a goal without deleting it; deleting a file is a
  human decision, not a tune.
- The `open-queue-tanks` constraint is the game's rule (at most two
  tanks); change it only if the user is playing a different queue.
