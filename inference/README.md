# inference - the INFERENCE LAYER

Facts in, the optimal composition out. The layer owns the right-hand
side of the equation:

```
STRATEGIES = CONSTRAINTS ∪ HEURISTICS       the playbook: markdown files in strategies/
COMP       = ARGMAX[ STRATEGIES( FACTS ) ]  the solver searches; the agent argues
```

Two things do the inferring, and it matters which is which:

- **The solver** is deterministic arithmetic. It reads the strategy files'
  frontmatter, scores every candidate six with the facts layer's metrics,
  and returns the best. No model, no API, no randomness beyond a seeded
  reference sample. It cannot read prose.
- **The agent** is a Claude Code session on the `/comp` skill. It reads
  the same facts and the prose of the same strategies and reconciles them
  where arithmetic cannot. It runs when you ask it to, never on its own,
  and it costs nothing beyond your subscription.

## How a strategy file works, and what it does not do

Drop a markdown file into `strategies/` and it is live: the solver reads
the directory on every call, the board's playbook panel shows it, the
`strategies` tool and the `strategy://` resources serve it, and
`load_authored` mirrors it into the `strategies` table so a recorded
comp can cite it. The frontmatter is the whole contract:

```markdown
---
name: Answer every revealed enemy
kind: heuristic                 # constraint | heuristic
category: matchup
direction: maximize             # heuristics: maximize | minimize
metric: team.coverage_share     # a key from the metrics registry
weight: 3
when: enemy.size >= 1           # optional guard, either kind
---
# Answer every revealed enemy
The share of revealed enemies at least one of our picks answers...
```

| kind | form | frontmatter | what the solver does |
| --- | --- | --- | --- |
| heuristic | | `metric`, `direction`, `weight` | normalises the metric to [0, 1] against a seeded sample of legal sixes for the board (flipped for minimize) and adds `weight x norm` |
| constraint | limit | `require: <expr>`, optionally `soft: true` + `penalty: <number>` | discards a candidate that fails (a soft one subtracts the penalty) |
| constraint | scored | `bonus: <expr>` and/or `penalty: <expr>`, optionally `when` | adds `weight x (bonus - penalty)` while `when` holds |
| constraint | prose | none of the above | nothing - the file is a ground rule the agent holds a comp to and the board shows |

**The engine does not infer a formula or a weight from the prose.** A
file with a name, a kind and a body is a prose constraint: served,
shown, cited, read by the agent, and worth exactly zero in the score.
To make it count, the frontmatter has to say how - a metric to weigh, a
limit to require, or a bonus to add - in the expression language below.
That can be written by hand, or asked of the `/tune` skill, which reads
the prose, proposes the frontmatter, and writes it through the `tune`
tool. Either way a person or a session decides; nothing here derives a
formula unasked.

Expressions are a whitelist, compiled once and validated against the
metrics registry when the catalog loads: the `team`, `enemy`, `matchup`,
`map`, `world` and `params` sections, arithmetic, comparisons, `and`,
`or`, `not`, `x if c else y`, and `min`, `max`, `abs`, `round`, `len`,
`int`, `float`, `bool`. A key that is not in the registry, or a `params.NAME`
not declared under `params:`, is refused at load, so a typo never scores
silently. `params:` (an indented block of NAME: number) are the dials an
expression reads as `params.NAME`.

Today the catalog is 38 files: 20 heuristics and 18 constraints (3
limits, 10 scored, 5 prose). `docs/strategies.md` is generated from them,
with the full vocabulary a strategy may reference.

## How the weights move

Weights do not learn on their own. Two paths change a file, both logged
in `strategies/tuning-log.md` with a reason and who asked:

- **`tune`** - one validated frontmatter edit: `weight` (0..10),
  `direction`, `soft`, `when`, `require`, `bonus`, `penalty`, `metric`, or a
  `params.NAME` dial. The edited file is loaded through the catalog before
  it is written, so an invalid change never lands. The `/tune` skill is
  the conversational front: "it keeps ignoring anti-heal" becomes a
  `tune` call and a re-run of the board to show the effect.
- **`fit_weights`** - evidence from your own games. `record_outcome` (the
  `/outcome` skill) stores how a match went; from ten decided matches the
  fit scores each recorded six on the solver's own scale and asks which
  heuristics ran higher in wins than in losses; from fifty it fits a ridge
  logistic regression, demeaned within each map. The proposal is a
  bounded nudge per weight (up to half the evidence, clamped to 0.25..6),
  shown as a dry run and applied through `tune` on request. Below the
  minimum the answer is "not yet".

## Layout

```
inference/
  README.md        this file
  __init__.py      the package's map
  strategies/      the playbook: one markdown file per constraint or heuristic,
                   and tuning-log.md
  catalog.py       reads, validates and mirrors the strategy files
  expr.py          the expression language the frontmatter uses
  solver.py        enumerate, prune, normalise, score, refine
  engine.py        infer(), evaluate(), board(): the solver plus citations
  record.py        the gates and the transcript for a decided comp
  outcomes.py      how a match went, stored beside the comp it played
  tune.py          one validated, logged edit to a strategy file
  fit.py           weight proposals from recorded outcomes
  serve.py         the HTTP service the compose stack's ui container calls
```

| file | purpose |
| --- | --- |
| `catalog.py` | Parses each file's frontmatter (a flat dialect plus one `params:` block), builds a `Strategy` with `kind`, `form`, compiled expressions and validation against the metrics registry, orders the catalog (constraints by form, then heuristics), mirrors it into the `strategies` table, and writes `docs/strategies.md`. |
| `expr.py` | A safe subset of Python expressions: the AST is checked once, compiled, and evaluated over a scope whose missing keys read as zero, so a metric that does not apply to a board never crashes a score. |
| `solver.py` | For a board: every role shape the hard limits allow around the locked picks; per-role pools ranked by a cheap prior; every candidate prepared (namespace, limit check, raw metric values) and scored with the frozen bounds; local search from the best few. The bounds come from a seeded reference sample of legal sixes for that map, side, enemy and bans, so `infer`, `evaluate` and the current comp share one scale and a score means the same thing across calls. |
| `engine.py` | `infer` (blue's optimal six around the locked picks), `evaluate` (a full six ranked against the field), `current` (the picks as they stand, partial or full), and `board` (both seats on opposite sides plus the current comp). Each result carries the picks with reasons and `[F#]` citations into the board's FactSet, the score breakdown per strategy, alternatives, and the prose constraints as "ground rules to reconcile against". |
| `record.py` | Storing a decided comp: the gates (six real heroes, every cited fact one the board showed), the tables (`recommendations`, picks, evidence), and a markdown transcript under `db/data/authored/recommendations/`. |
| `outcomes.py` | Storing a match result - win, loss or draw, the map and side, both sixes, the bans, the recommendation played - and the summary the fit reads. |
| `tune.py` | `tune(id, field, value, reason)`: edit the frontmatter, validate by loading the catalog with the edited file, write, re-mirror, log. |
| `fit.py` | `propose` and `apply`: the two evidence tiers above, and the bounded nudge. |
| `serve.py` | `/board`, `/infer`, `/evaluate`, `/strategies`, `/health`, `POST /record` - the same functions, over HTTP, for a board that runs in another container. |

## The skills

| skill | does |
| --- | --- |
| `/comp` | the agent: pulls map, side, bans, red and locked blue picks out of what you say, calls `infer` (or `board`), reads `facts`, adopts or improves on the solver's optimum against the prose constraints, answers with `[F#]` citations, and records the result through `record` |
| `/tune` | a manual tune, or a fit from outcomes, through the `tune` and `fit_weights` tools; shows the effect on the board |
| `/outcome` | records how a match went through `record_outcome` |
| `/up` | brings the stack up and current before a game |

All of it runs on the MCP tools the data layer serves (`infer`,
`evaluate`, `board`, `facts`, `strategies`, `record`, `record_outcome`,
`tune`, `fit_weights`, `tuning_log`), which is what makes a session and
the board see the same numbers.
