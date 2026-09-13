---
name: Cycle cooldowns faster
kind: heuristic
category: tempo
direction: minimize
metric: team.cooldown_median
weight: 0.5
---
# Cycle cooldowns faster

Median cooldown across every ability on the team. Short-cooldown kits
re-engage first and fight constantly; long ones make each fight
decisive. A mild preference for uptime, because under optimal play the
side that dictates fight frequency dictates the match.
