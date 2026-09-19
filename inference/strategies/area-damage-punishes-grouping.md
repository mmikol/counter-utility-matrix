---
name: Area damage punishes grouping
kind: heuristic
category: damage
metric: team.aoe_damage
direction: maximize
weight: 0.5
when: matchup.style_lean_red == 'brawl'
---
# Area damage punishes grouping

Damage that hits an area is worth more than its number against a team that stands together. A brawl line holds by grouping, and splash from Junkrat and Ashe's dynamite punishes it while single-target damage picks one target and gets healed. Kit pieces that damage an area are counted across the six, read while red's majority style is brawl.
