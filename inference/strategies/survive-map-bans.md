---
name: Survive this map's ban screen
kind: heuristic
category: meta
metric: team.map_availability
direction: maximize
weight: 1.5
when: map.known == 1
---
# Survive this map's ban screen

On a known map the ban screen is the map's own, and a hero that is safe on the ladder can be the first vote here. The map's ban rates replace the all-ranks ones pick by pick, so the chance the six survives is the map's chance, not the average. The product of one minus each pick's ban rate on the map is read.
