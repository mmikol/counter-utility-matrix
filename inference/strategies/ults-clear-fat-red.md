---
name: Ultimates clear a fat red
kind: heuristic
category: damage
metric: team.ult_damage_total
direction: maximize
weight: 1
when: enemy.pool_total >= 1900
---
# Ultimates clear a fat red

Against a red that fields 1,900 or more summed hit points, steady fire alone does not break the line and the fight waits for ultimates. A bunker of Orisa, Bastion and Torbjörn is broken by waiting for ults to come in, and a Graviton Surge with a team-wipe ultimate behind it is the plan against any six too fat to chew. Summed maximum damage across the six's damage ultimates is measured, read while red's summed pool is 1,900 or more.
