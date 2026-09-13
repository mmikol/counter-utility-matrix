---
name: What the score is
kind: strategy
category: assumptions
---
# What the score is

For every candidate six, the solver computes the same team, enemy and
matchup metrics the board shows as facts, then sums: each goal's weight
times its metric normalised to [0, 1] across the candidates (flipped
for minimize), plus each scored strategy's weight times its bonus minus
penalty while its condition holds, minus soft-constraint penalties. Hard
constraints prune before any of that. A strategy with no bonus or
penalty is prose alone - the session reads it, the board shows it.

To tune, edit a file: raise a weight, add a `when`, change a threshold
under `params`. The catalog is validated on load - a metric name that
does not exist is an error, not a silent zero - and `db_docs`
regenerates docs/heuristics.md from the files.
