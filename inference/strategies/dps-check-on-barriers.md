---
name: Barriers are a DPS check
kind: heuristic
category: damage
metric: team.dps_floor
direction: maximize
weight: 0.25
when: matchup.barrier_need >= 1200
---
# Barriers are a DPS check

When red fields 1,200 or more barrier HP, every point of per-second damage on the six goes into the shield. A Cassidy shooting through 2,000 HP alone because his Genji and Widowmaker do no shield damage is the check failed. Summed published per-second damage is measured, read while red's barrier HP is 1,200 or more.
