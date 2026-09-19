---
name: Bring the map's specialists
kind: heuristic
category: map
metric: team.map_specialists
direction: maximize
weight: 0.5
when: map.known == 1
---
# Bring the map's specialists

A hero who runs well above their own average on this map is a specialist worth building around. Some kits fit one map far better than their own average shows, a Widowmaker on Circuit Royal, a Lúcio on Ilios, and the map rates catch the gap. Picks running 2.5 points or more over their own baseline win rate on the selected map are counted.
