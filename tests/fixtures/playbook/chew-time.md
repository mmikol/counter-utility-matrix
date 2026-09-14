---
name: Chew through them faster
kind: heuristic
category: matchup
direction: minimize
metric: matchup.chew_time_ours
weight: 1
when: enemy.size >= 1
---
# Chew through them faster

Their total pool divided by our damage floor: seconds of unmitigated
fire to delete the enemy team. Crude and labelled crude on the board -
no healing, no misses - but a two-to-one asymmetry in the floor is real
information about who wins a straight trade.
