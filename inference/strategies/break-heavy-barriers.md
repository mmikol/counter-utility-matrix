---
name: Break a heavy barrier line
kind: heuristic
category: matchup
metric: team.dps_floor
direction: maximize
weight: 0.5
when: matchup.barrier_need >= 1200
---
# Break a heavy barrier line

A Reinhardt or Ramattra barrier line only moves when something melts it, and the shield busters are the picks with a high sustained damage figure: Bastion and Junkrat chew barriers that hitscan poke never dents. Damage per second decides whether the barrier is down before their fire finishes ours. Measured as the summed published per-second damage of the team, read while red fields 1200 or more barrier health.
