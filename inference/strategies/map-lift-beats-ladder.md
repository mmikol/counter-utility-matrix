---
name: Map lift beats the ladder rate
kind: constraint
category: map
when: map.known == 1 and team.map_win_mean > team.win_mean
bonus: min((team.map_win_mean - team.win_mean) / params.LIFT_STEP, 2) * 0.5
params:
  LIFT_STEP: 2
---

# Map lift beats the ladder rate

A hero winning more on this map than on the ladder has something in the kit that this ground rewards. The community's map-synergy measure is the map win rate minus the patch baseline: a nerfed hero at 43 percent overall who still pulls 49 percent on Dorado has structural synergy with Dorado. It earns half a point per 2 points of mean lift of the six's map win rate over its ladder win rate, up to 4 points of lift.
