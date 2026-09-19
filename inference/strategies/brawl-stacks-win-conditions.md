---
name: Brawl stacks fight-winning ultimates
kind: heuristic
category: shape
metric: team.dmg_ults
direction: maximize
weight: 0.25
when: team.style_lean == 'brawl'
---
# Brawl stacks fight-winning ultimates

A brawl comp forces team fights often, so it wants as many fight-winning ultimates as it can farm. Poke can wait for neutral to tilt, but brawl commits every fight and needs a go button when it does. Measured as the count of ultimates carrying a damage figure, read only while brawl is the majority style.
