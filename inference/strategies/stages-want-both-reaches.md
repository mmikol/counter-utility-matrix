---
name: Stages ask for both reaches
kind: constraint
category: map
when: map.stages >= 3
bonus: (0.5 if team.range_max >= params.LONG_GUN else 0) + min(team.melee, 1) * 0.5
params:
  LONG_GUN: 60
---

# Stages ask for both reaches

A Control or Flashpoint map is 3 or 5 different stages with one six for all of them, and the stages disagree about range. Nepal's Sanctum needs a ranged tank to pressure snipers across long sightlines while its Shrine is melee-range combat on small stairs. It earns half a point for a longest range at or over the dial, 60 m by default, and half a point for a melee pick, on maps with 3 or more stages.
