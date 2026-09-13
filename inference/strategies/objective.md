---
name: What the score is
kind: constraint
category: assumptions
prose: true
---
# What the score is

For every candidate six, the solver computes the same team, enemy and
matchup metrics the board shows as facts, then sums: each heuristic's weight
times its metric normalised to [0, 1] across the candidates (flipped
for minimize), plus each scored constraint's weight times its bonus minus
penalty while its condition holds, minus soft limits' penalties. Hard
limits prune before any of that. A constraint with neither a limit nor a bonus
or penalty is prose alone - the session reads it, the board shows it.
STRATEGIES = CONSTRAINTS ∪ HEURISTICS; the score is STRATEGIES( FACTS ).

To tune, edit a file: raise a weight, add a `when`, change a threshold
under `params`. The catalog is validated on load - a metric name that
does not exist is an error, not a silent zero - and `db_docs`
regenerates the catalog in docs/inference.md from the files.
