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

A poke six that carries one short-range pick carries one pick that must walk into the fight the comp is refusing. Measured as the shortest longest-range on the team, read only while poke is the majority style.
