---
name: Popular here and winning here
kind: constraint
category: map
when: map.known == 1 and team.map_win_mean >= params.GOOD_WIN
bonus: min(max(team.map_pick_mass - params.MASS_FLOOR, 0) / params.MASS_SPAN, 1) * 0.5
params:
  GOOD_WIN: 50
  MASS_FLOOR: 40
  MASS_SPAN: 40
---

# Popular here and winning here

A six the map's lobby both picks heavily and wins with is a six the map has already tested. Zenyatta is picked 16.4 percent on King's Row against 11 to 12 on the Flashpoint maps, and the pick rate is the sample behind the win. It earns up to half a point as the six's summed map pick rate runs from 40 to 80, while the mean win rate on the map is at or over 50.
