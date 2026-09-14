---
name: What the score is
kind: assumption
category: assumptions
---
# What the score is

For every candidate six, the solver computes the same team, enemy and
matchup metrics the board shows as facts, then sums: each heuristic's weight
times its metric normalised to [0, 1] against a fixed reference sample of
comps for the board (flipped for minimize), plus each scored constraint's
weight times its bonus minus penalty while its condition holds, minus soft
limits' penalties. Hard limits prune before any of that. An assumption is
prose alone - the session reads it, the board shows it, nothing is scored.
STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS; the score is
STRATEGIES( FACTS ), and 100 on the board is the best six the solver found.

To tune, change a file through the `tune` tool: raise a weight, add a
`when`, turn a threshold under `params`. The catalog is validated on load -
a metric name that does not exist is an error, not a silent zero - and
`db_docs` regenerates the catalog in docs/inference.md from the files.
