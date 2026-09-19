---
name: Popular here and losing here
kind: constraint
category: map
when: map.known == 1 and team.map_win_mean < params.TRAP_WIN
penalty: min(max(team.map_pick_mass - params.MASS_FLOOR, 0) / params.MASS_SPAN, 1) * 0.5
params:
  TRAP_WIN: 48
  MASS_FLOOR: 40
  MASS_SPAN: 40
---

# Popular here and losing here

A six of heroes the map's lobby picks heavily but loses with is a six of trap picks. The map's pick rate is the crowd's belief about the map and its win rate is the result, and where the two disagree the result is the one to trust. It charges up to half a point as the six's summed pick rate on the map runs from 40 to 80, while the mean win rate on the map is under 48.
