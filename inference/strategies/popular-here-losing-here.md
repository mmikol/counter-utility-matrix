---
name: Popular here and losing here
kind: constraint
category: map
when: map.known == 1 and team.map_win_mean < params.TRAP_WIN
penalty: min(team.map_pick_mass / params.TRAP_MASS, 1) * 1
params:
  TRAP_WIN: 50
  TRAP_MASS: 90
---
# Popular here and losing here

A six of heroes the map's lobby picks heavily but loses with is a six of trap picks, popular here for reasons the rates do not reward. The map's pick rate is the crowd's belief about the map and its win rate is the result, and where the two disagree the result is the one to trust. It charges up to a point, scaled by the six's summed pick rate on the map against a dial of 45, while the mean win rate on the map is under 50.
