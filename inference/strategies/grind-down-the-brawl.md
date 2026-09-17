---
name: Grind the brawl down
kind: heuristic
category: damage
metric: team.dps_floor
direction: maximize
weight: 0.75
when: matchup.style_lean_red == 'brawl'
---
# Grind the brawl down

A brawl six is the most durable shape in the game, and durable things fall to sustained damage rather than to a single hit. Heroes that pour damage per second into the ball chew through the armor and the healing a brawl walks in behind. Measured as summed published damage per second, read only while red's majority playstyle is brawl.
