---
name: Brawl swings at melee
kind: heuristic
category: damage
metric: team.melee
direction: maximize
weight: 0.5
when: team.style_lean == 'brawl'
---
# Brawl swings at melee

A brawl six earns its damage and its ultimate charge at arm's length, and a melee weapon is the one that cannot miss there. Reinhardt's hammer and Brigitte's flail do their full damage at exactly the range the brawl closes to. Measured as picks with a melee weapon, read only while brawl is the majority style.
