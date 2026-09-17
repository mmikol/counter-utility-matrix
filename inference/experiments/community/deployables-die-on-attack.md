---
name: Deployables die on attack
kind: heuristic
category: side
metric: team.deployables
direction: minimize
weight: 0.5
when: map.side == 'attack'
---
# Deployables die on attack

A deployable placed under fire is a deployable already lost. On attack the team moves through chokes the defence has sighted, so a turret or a wall goes down before it earns its cooldown, and the pick that carries it is playing a defender's kit on the wrong side. Picks with deployables are counted, read on the attacking side of an Escort or Hybrid map, and fewer is better.
