---
name: Chokes reward crowd control
kind: heuristic
category: map
metric: team.cc_count
direction: maximize
weight: 1
when: map.chokes >= 0.5 or map.interiors >= 0.5
---
# Chokes reward crowd control

Where a map funnels both teams into a choke, crowd control decides who gets through it. A stun, a wall or a knockback at a doorway takes a pick out of the fight at the one moment the whole team is committed, and enclosed space leaves nowhere to dodge it. Picks with a crowd-control tool are counted, read on maps whose chokes or interiors stand 0.5 or more above the ordinary map's.
