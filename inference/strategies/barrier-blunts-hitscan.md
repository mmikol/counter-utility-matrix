---
name: A barrier blunts their hitscan
kind: heuristic
category: matchup
metric: team.barrier_hp
direction: maximize
weight: 0.75
when: enemy.hitscan >= 2
---
# A barrier blunts their hitscan

Hitscan damage has no travel time to dodge, so the soft counter to it is a barrier in the line of fire: a shield tank turns a Widowmaker duel into a shoot-the-barrier duel and gives the squishies safe cover to cross a sightline. Barrier health is how long that cover lasts against sustained hitscan fire. Measured as the summed barrier health the team fields, read while 2 or more red picks have a hitscan weapon.
