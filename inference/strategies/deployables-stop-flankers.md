---
name: Deployables stop the flankers
kind: heuristic
category: matchup
metric: team.deployables
direction: maximize
weight: 0.75
when: matchup.dive_pressure >= 4
---
# Deployables stop the flankers

A placed object fights a flanker while the team looks elsewhere: turrets counter flank pressure, a wall cuts the diver off from the target, and a tree or a barrier gives the backline something to stand behind. Symmetra is rated one of the better damage picks in coordinated play for her turrets against flanks, and Torbjörn is the answer offered to a flanking Anran. Measured as the count of picks with deployables, read while 4 or more red picks carry a movement tool.
