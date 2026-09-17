---
name: Barriers are a DPS check
kind: heuristic
category: damage
metric: team.dps_count
direction: maximize
weight: 1
when: matchup.barrier_need >= 1200
---
# Barriers are a DPS check

When red fields 1,200 or more barrier HP, every pick with a published damage figure is another gun on the shield, and a six with picks that do no barrier damage fails the check. An enemy Reinhardt shield is a team DPS check that has to be passed, and a Cassidy solo shooting through 2,000 HP because his Genji and Widowmaker do no shield damage is the check failed. Picks whose kit publishes a per-second damage figure are counted, read while red's barrier HP is 1,200 or more.
