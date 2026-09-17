---
name: Match a two-tank front
kind: heuristic
category: shape
metric: team.tanks
direction: maximize
weight: 1
when: enemy.tanks >= 2
---
# Match a two-tank front

Against two red tanks one tank of ours holds neither the front nor the backline, because pushing through a double front takes both tanks and the second is what lets one peel. The community says taking ground against two tanks requires both of yours, and that the second tank is what makes the pairings and the peel possible. Measured as our tank count, read while red has revealed 2 or more tanks.
