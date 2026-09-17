---
name: Heavy fire finds the weakest
kind: heuristic
category: durability
metric: team.pool_min
direction: maximize
weight: 1
when: enemy.dps_floor >= 900
---
# Heavy fire finds the weakest

Against a red whose damage floor is 900 or more per second, the six is only as durable as its smallest pool, because focus fire lands there first. A pick walks out of cover and is focused from 100 to 0 in two seconds, and a 200 HP hero missing 20 to 60 HP is liable to be deleted for doing its job, so the comp into heavy fire raises its floor. The weakest pick's pool is measured, read while red's per-second damage floor is 900 or more.
