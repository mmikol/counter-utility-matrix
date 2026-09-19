---
name: Popular here and winning here
kind: constraint
category: map
when: map.known == 1 and team.map_win_mean >= params.GOOD_WIN
bonus: min(team.map_pick_mass / params.POPULAR_MASS, 1) * 0.5
params:
  GOOD_WIN: 50
  POPULAR_MASS: 90
---

# Popular here and winning here

A six the map's lobby both picks heavily and wins with is a six the map has already tested. Zenyatta's King's Row rate is read as the real indicator because he is picked 3 to 4 times as often there as on Flashpoint, and the pick rate is the sample behind the win. It earns up to half a point, scaled by the six's summed map pick rate against a dial of 90, while the mean win rate on the map is at or over 50.
