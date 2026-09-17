---
name: Outdamage their floor
kind: heuristic
category: damage
metric: matchup.dps_diff
direction: maximize
weight: 1
when: matchup.chew_time_theirs < 999
---
# Outdamage their floor

The side with the higher damage floor forces the other to answer every exchange with healing, and healing plus mitigation eventually loses to more damage. Three damage picks outdamage three supports whatever those supports heal, so the comparison of floors is the comparison of who gets to walk forward. Our summed per-second damage minus red's is measured, read once red has revealed damage.
