---
name: Cycle ultimates faster than red
kind: heuristic
category: tempo
metric: team.ult_cost_mean
direction: minimize
weight: 0.25
when: enemy.ult_cost_mean >= 2250
---
# Cycle ultimates faster than red

When red's ultimates are expensive, a six whose ultimates are cheap reaches its win conditions a fight earlier. Ultimates charge on a point cost balanced to the hero's damage and healing, so a Coalescence or Pulse Bomb comes around while a Graviton Surge is still building. Mean published ultimate cost across the six is measured, lower being faster, read while red's mean cost is 2,250 or more.
