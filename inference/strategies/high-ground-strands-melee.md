---
name: High ground strands melee
kind: heuristic
category: map
metric: team.melee
direction: minimize
weight: 0.5
when: map.style_top == 'dive'
---
# High ground strands melee

On a map built around high ground a melee pick has no way to touch an enemy standing above and no quick way up. Reinhardt is named as the tank who suffers most where high ground matters, with nothing to throw at it but a Fire Strike, and brawl's movement tools are said to have no vertical component at all. Picks with a melee weapon are counted, minimised where the map rewards dive.
