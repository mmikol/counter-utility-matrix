---
name: Last pick answers what is shown
kind: heuristic
category: matchup
metric: team.coverage_share
direction: maximize
weight: 0.5
when: enemy.size >= 5
---

# Last pick answers what is shown

With five or six red picks revealed, the last pick in is the counter pick and the six should answer as much of the enemy board as it can. A pick made into a fully revealed six loses nothing to a later swap, so the counters table is read in full. Measured as the share of revealed red picks that at least one of ours answers, while five or more are revealed.
