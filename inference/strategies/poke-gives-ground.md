---
name: Poke needs an exit
kind: heuristic
category: shape
metric: team.mobility_count
direction: maximize
weight: 0.75
when: team.style_lean == 'poke'
---

# Poke needs an exit

A poke six is the weakest comp once the distance is closed, so it gives ground and resets the distance rather than taking the fight. A poke pick with no movement tool cannot give ground. Measured as picks with a movement or evasive ability, read only while poke is the majority style.
