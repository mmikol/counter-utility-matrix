---
name: Last pick answers what is shown
kind: heuristic
category: matchup
metric: matchup.coverage_share
direction: maximize
weight: 1
when: enemy.size >= 5
---
# Last pick answers what is shown

Once red has revealed five or six picks, the last pick in is the counter pick, and the six should answer as much of what stands on the other side as it can. A draft's last seat sees the whole enemy board and a pick chosen there into a fully revealed six loses nothing to a later swap, so the counters table is read in full rather than lightly. Measured as the share of revealed red picks that at least one of ours answers, while five or more are revealed.
