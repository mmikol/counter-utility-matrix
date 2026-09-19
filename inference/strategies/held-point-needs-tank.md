---
name: A held point needs its tank
kind: heuristic
category: durability
metric: team.pool_total
direction: maximize
weight: 0.25
when: map.stages >= 3
---
# A held point needs its tank

On Control and Flashpoint the team holds a point for as long as it can, and losing the tank first on a held point is called a huge disadvantage. Health, shield and armor summed across the six is measured, read on maps with 3 or more stages.
