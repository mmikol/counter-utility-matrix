---
name: Pick into what the map rewards
kind: heuristic
category: map
metric: team.style_fit
direction: maximize
weight: 2.5
when: map.known == 1
---
# Pick into what the map rewards

A six built of the playstyle a map rewards wins the fights that map sets up. The authored map notes tag each map with the style its geometry favours, brawl in corridors and chokes, poke across long sightlines, dive where high ground stacks, and a hero carries the style tags its kit earns. The share of the six tagged with the map's rewarded style is the measure, and it reads as 0 without a map.
