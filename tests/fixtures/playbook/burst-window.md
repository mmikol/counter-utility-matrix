---
name: Keep a kill window through their healing
kind: heuristic
category: matchup
direction: maximize
metric: matchup.burst_vs_heal
weight: 1
when: enemy.size >= 1
---
# Keep a kill window through their healing

Our biggest single damage figure minus their biggest single heal. When
it is positive, one cooldown deletes a target through the save; when it
is negative, every pick has to stack damage to kill anything, and
optimal-play enemies do not stand still for that.
