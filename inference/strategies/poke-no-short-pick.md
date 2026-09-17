---
name: Poke carries no short pick
kind: heuristic
category: shape
metric: team.range_min
direction: maximize
weight: 1
when: team.style_lean == 'poke'
---
# Poke carries no short pick

A poke six that carries one short-range pick carries one pick that must walk into the fight the comp is refusing. A poke comp is the weakest option once the teams have closed, so the pick that only works close either idles through the poke phase or dies starting the brawl alone. Measured as the shortest longest-range on the team, read only while poke is the majority style.
