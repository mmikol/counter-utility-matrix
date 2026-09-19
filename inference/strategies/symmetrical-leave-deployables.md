---
name: Symmetrical modes leave deployables behind
kind: heuristic
category: map
metric: team.deployables
direction: minimize
weight: 0.5
when: map.known == 1 and map.sided == 0
---

# Symmetrical modes leave deployables behind

On Control, Push and Flashpoint the fight moves, from the neutral centre to the next point or down the robot's lane, and a deployable set for one position is left behind by the next. Picks with deployables are counted, minimised on symmetrical maps.
