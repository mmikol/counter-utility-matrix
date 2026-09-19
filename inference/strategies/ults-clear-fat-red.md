---
name: Ultimates clear a fat red
kind: heuristic
category: damage
metric: team.ult_damage_total
direction: maximize
weight: 0.25
when: enemy.pool_total >= 2050
---

# Ultimates clear a fat red

Against a red that fields 2,050 or more summed hit points, steady fire does not break the line and the fight waits for ultimates. A bunker of Orisa, Bastion and Torbjörn is broken by waiting for ults to come in. Summed maximum damage across the six's damage ultimates is measured, read while red's summed pool is 2,050 or more.
