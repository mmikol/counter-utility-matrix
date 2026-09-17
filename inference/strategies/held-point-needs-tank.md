---
name: A held point needs its tank
kind: heuristic
category: durability
metric: team.pool_min
direction: maximize
weight: 0.75
when: map.stages >= 3
---
# A held point needs its tank

On Control and Flashpoint the team holds a point for as long as it can, and the hold is lost the moment the first body drops. The weakest pool on the six is where the first pick lands, and losing the tank first on a held point is called a huge disadvantage. The smallest effective HP on the team is the measure, read on maps with 3 or more stages.
