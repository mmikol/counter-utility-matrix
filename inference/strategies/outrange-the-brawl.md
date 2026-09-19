---
name: Outrange the brawl
kind: heuristic
category: matchup
metric: team.range_median
direction: maximize
weight: 1.5
when: matchup.style_lean_red == 'brawl'
---

# Outrange the brawl

Poke beats brawl because a brawl has to cross open ground to do anything, and every metre of that crossing is a free shot for the longer reach. Measured as the median of each pick's longest published range, read only while red's majority playstyle is brawl.
