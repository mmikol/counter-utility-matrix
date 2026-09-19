---
name: A barrier eats the big ultimate
kind: heuristic
category: matchup
metric: team.barrier_hp
direction: maximize
weight: 0.5
when: matchup.ult_threat >= 1500
---
# A barrier eats the big ultimate

Earthshatter, Self-Destruct and a Deadeye all stop at a barrier, and the first counter to a Reinhardt ultimate is a Reinhardt barrier of one's own. Barrier health is what lets that block survive the hit instead of breaking under it. Measured as the summed barrier health the team fields, read while red's summed damage-ultimate ceiling is 1,500 or more.
