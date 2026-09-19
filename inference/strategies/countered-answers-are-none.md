---
name: Answered answers are no answers
kind: heuristic
category: matchup
metric: team.exposure_edges
direction: minimize
weight: 0.75
when: enemy.size >= 1
---
# Answered answers are no answers

An answer that red already counters is not an answer: the pick meant to solve one enemy spends the match dodging another. Every counter to GOATS could be shut down by a swap to Widowmaker, and the ladder's version is the swap that counters the enemy tank but is countered by several others on their team. Measured as the total of counter edges from revealed red picks onto ours, kept low once red reveals a pick.
