---
name: Each map has its own meta
kind: heuristic
category: map
metric: team.map_pick_mass
direction: maximize
weight: 0.5
when: map.known == 1
---
# Each map has its own meta

What a lobby fields changes with the map, so the map's own pick rates are the meta that matters once the map is known. Sightlines, high ground and the mode decide which kits get picked here, and the ladder's global pick rate hides that. The summed pick rate of the six on the selected map is read.
