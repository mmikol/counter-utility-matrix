---
name: Cycle ultimates faster than red
kind: heuristic
category: tempo
metric: team.ult_cost_mean
direction: minimize
weight: 0.25
when: enemy.ult_cost_mean >= 2450 and enemy.size >= 3
---
# Cycle ultimates faster than red

When red's ultimates are expensive, a six whose ultimates are cheap reaches its win conditions a fight earlier. Ultimates charge on a published point cost, so a Pulse Bomb at 1,375 comes around while a Coalescence at 2,700 is still building. Mean published ultimate cost across the six is measured, lower being faster, read while three or more red picks are revealed and their mean cost is 2,450 or more.
