---
name: Poke needs reach
kind: heuristic
category: shape
metric: team.range_median
direction: maximize
weight: 1
when: team.style_lean == 'poke'
---
# Poke needs reach

A poke comp wins the chip war before the fight closes, and it can only chip what it can reach. A short-range pick in a poke six is either idle during the poke phase or walking forward alone. Measured as the median of each pick's longest published range, read only while poke is the majority style.
