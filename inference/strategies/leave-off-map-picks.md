---
name: Leave off-map picks at home
kind: heuristic
category: map
metric: team.map_offmap
direction: minimize
weight: 0.25
when: map.known == 1
---

# Leave off-map picks at home

A hero running well below its own average here is a liability the rest of the comp carries, and the map rates show the cost before the fight does. Picks running 2.5 points or more under their own baseline win rate on the selected map are counted, and fewer is better.
