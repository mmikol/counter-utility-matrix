---
name: Brawl maps stack win conditions
kind: heuristic
category: damage
metric: team.dmg_ults
direction: maximize
weight: 0.75
when: map.style_top == 'brawl'
---
# Brawl maps stack win conditions

A brawl map decides its fights in the commit, and the six that carries more fight-winning ultimates into the commit wins more of them. Poke is played on the maps where it can win before the neutral ends and so needs to stack fewer teamfight win conditions, and brawl maps ask the opposite. Ultimates carrying a damage figure are counted, read where the map rewards brawl.
