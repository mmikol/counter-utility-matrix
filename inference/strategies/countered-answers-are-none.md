---
name: Answered answers are no answers
kind: heuristic
category: matchup
metric: team.exposure_edges
direction: minimize
weight: 0.75
when: team.coverage >= 1
---
# Answered answers are no answers

An answer that red already counters is not an answer, because the pick meant to solve one enemy spends the match dodging another. Every counter to GOATS could be shut down by a swap to Widowmaker, and the ladder's version is the swap to a hero that counters the enemy tank but is countered by multiple other people on the enemy team. Measured as the total of counter edges from revealed red picks onto ours, kept low while the six answers at least one red pick.
