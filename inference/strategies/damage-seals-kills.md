---
name: Damage seals the kills
kind: heuristic
category: damage
metric: team.dps_floor
direction: maximize
weight: 1.5
---
# Damage seals the kills

A comp needs enough sustained damage to finish what it starts, since healing alone holds space but never takes it. When the whole line pours out healing and little damage, nobody is bursted down and nobody is held back, so the enemy walks forward through it; every damage pick and at least one support has to add pressure. The sum of each pick's best published per-second damage figure is measured, a floor that ignores misses and healing.
