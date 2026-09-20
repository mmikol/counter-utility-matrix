---
name: Vertical maps reward fliers
kind: heuristic
category: map
metric: team.flyers
direction: maximize
weight: 0.25
when: map.high_ground >= 0.5
---

# Vertical maps reward fliers

A map with high ground everywhere rewards the picks that travel between its levels without a staircase. Echo is named as the fill pick for maps with verticality, and the maps with the most high ground are called best for heroes that move easily between low and high ground. Picks that fly or hover are counted, read where the map's high ground stands 0.5 or more above the ordinary map's.
