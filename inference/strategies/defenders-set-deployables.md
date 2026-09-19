---
name: Defenders set deployables
kind: heuristic
category: side
metric: team.deployables
direction: maximize
weight: 1
when: map.side == 'defense'
---
# Defenders set deployables

Defenders arrive first and get to build the ground they hold. Walls, barriers and lamps placed before the attackers reach the choke turn a position into a fortification, and a kit with something to place is worth more when it starts set up than when it has to place under fire. Picks with deployables are counted, barriers and walls among them, read on the defending side of an Escort or Hybrid map.
