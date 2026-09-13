---
name: strategy
description: Add a strategy to overwatch-db's playbook from three things the user gives - a name, a kind (constraint or heuristic), and a prose description - and infer the rest (the metric, direction and weight of a heuristic; the limit or the when/bonus/penalty and params of a constraint), validate it and store it. Use when the user wants to add a rule, a constraint, a heuristic or a strategy, says "the solver should ...", "add a strategy", "make it prefer/avoid ...", or asks to finish a draft strategy file.
---

You are the inference the engine does not do. The solver in
`inference/solver.py` is deterministic arithmetic: it scores only what a
strategy file's frontmatter states. The user writes the *what* - a name,
a kind, and prose saying what the strategy means and why - and you write
the *how*: the frontmatter that makes the solver act on it. Everything
goes through the `overwatch-db` (or `overwatch-db-docker`) MCP server,
which validates the file against the catalog before it exists, mirrors
it into the `strategies` table, and logs it in
`inference/strategies/tuning-log.md`. Nothing is written by hand.

## What to ask for

Three things, and only these. Ask for whatever is missing in one
message; do not ask for weights, metrics or expressions - inferring those
is your job.

1. **The name** - a short imperative or a claim ("Shut off a heavy heal
   line", "Two supports must actually heal").
2. **The kind**: a **constraint** (something the comp must or should do:
   a limit, a reward, a penalty, or a ground rule) or a **heuristic**
   (something to have more or less of, measured).
3. **The prose** - two to six sentences: what it means, when it applies,
   why it matters. Quote the game, not the engine.

Derive the id from the name (lowercase-kebab, `shut-off-a-heavy-heal-line`
becomes `shut-off-heals` if the user prefers short), and the category from
the prose (matchup, sustain, damage, durability, shape, map, side, tempo,
uncertainty, assumptions ...); confirm both in passing, never as a question.

## How to infer the rest

1. Read the vocabulary: the `metrics` tool lists every key a strategy may
   reference with its meaning - `team.*` for our side, `enemy.*` for the
   same numbers on the red side, `matchup.*` for the two compared,
   `map.*`, `world.*` - and which are text (usable in a `when`, never as
   a heuristic's metric).
2. Read the catalog: the `strategies` tool shows every existing file with
   its form and expressions. Do not duplicate one that already says it
   (say so and offer `/tune` instead); do match the house style - weights
   1 to 4 for heuristics, bonuses and penalties of 0.5 to 2 per unit for
   scored constraints, `min(x, n)` to cap a reward, `params:` for any
   threshold a person might want to turn.
3. Decide, from the prose:
   - **heuristic**: one numeric `metric`, its `direction`, a `weight`. "More
     sustain" is `team.heal_peak_total maximize`; "fewer one-dive targets"
     is `team.squish_count minimize`. If no single metric captures it,
     say which comes closest and why, or say that no metric exists yet -
     that is a code change in `ui/facts/compute.py`, not a frontmatter
     trick.
   - **constraint, limit**: a `require` that must hold ("at most two
     tanks" is `team.tanks <= 2`); `soft: true` with a numeric `penalty`
     when it should cost rather than forbid.
   - **constraint, scored**: a `when` guard and a `bonus` and/or
     `penalty` expression, with `params:` for thresholds ("one anti-heal
     against a heavy heal line" is `when: enemy.heal_ratio >= params.HEAL_RATIO`,
     `bonus: min(team.antiheal, 1) * 1.5`, `params: {HEAL_RATIO: 1.0}`).
   - **constraint, prose**: `prose: true` when the prose is a ground rule
     the session should hold a comp to but nothing measurable ("trust the
     kit over stale rates"). Say that it will not move the score.
4. Store it: `add_strategy` with `id`, `name`, `kind`, `body` (the prose,
   verbatim), the inferred fields, and a `reason` that quotes the sentence
   of the prose each field follows from. A key that is not in the
   vocabulary or an expression that does not parse is refused and nothing
   is written - fix and call again. For a file the user dropped in with
   only a name, a kind and prose (the catalog shows it as a *draft*), use
   `infer_strategy` with the same fields instead.
5. Show the effect: run `board` (or `infer`) for the board the user is on,
   or a representative one (King's Row against a heal-heavy red, say),
   and point at the new line in the breakdown. If the strategy never
   applies on that board, say so and pick one where it does.
6. Report in three lines: where it landed (the file, the table, the log
   line), what it does in the solver's terms, and the one dial a person
   might turn (`/tune` changes it).

## Drafts the engine derives itself

A file dropped into `inference/strategies/` with only a name, a kind and
prose is a draft. On a host where the claude CLI is signed in, the engine
derives its frontmatter without you: `load_authored`, `orchestrator.py up` and
the `derive_strategies` tool ask `claude -p` the same question this skill
answers and store the result through the same validated path. This skill
is the interactive version - use it when the user wants to see and
discuss the inference, or when `strategies` shows a draft that the
engine could not complete (its log line says why).

## Ground rules

- Three inputs from the user, everything else inferred and explained:
  never ask the user for a metric key, a weight or an expression.
- One file per strategy; never overwrite - `tune` and `infer_strategy`
  change an existing one, deleting is a human decision.
- Players are assumed to play optimally: a strategy encodes the game,
  not a lobby's habits. For "we keep losing to X", prefer `/outcome` and
  `/tune`'s fit.
- Keep the prose the user's; the frontmatter is yours. If you changed a
  word of the prose, say which.
