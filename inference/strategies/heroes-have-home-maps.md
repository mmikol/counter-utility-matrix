---
name: Heroes have home maps
kind: heuristic
category: map
metric: team.map_strategy_hits
direction: maximize
weight: 0.25
when: map.known == 1
---
# Heroes have home maps

A pick whose best maps include this one belongs in the comp more than one whose do not. A hero's best maps are the three where Blizzard's rates lift it most over its own overall rate. Picks whose three best maps include the selected map are counted.
