---
name: Win on this ground
kind: heuristic
category: map
metric: team.map_win_mean
direction: maximize
weight: 2
when: map.known == 1
---
# Win on this ground

A comp that wins on this map is measured by what its picks have already won here. Per-map win rates are the closest measured thing to a hero's fit for the ground, and they catch what the geometry notes miss, a long walk back, a well, a bridge. The mean of the six's win rates on the selected map is the measure, read only while a map is set.
