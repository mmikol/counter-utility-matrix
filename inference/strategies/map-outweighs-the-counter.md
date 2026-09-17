---
name: The map outweighs the counter
kind: heuristic
category: map
metric: team.map_win_mean
direction: maximize
weight: 1
when: map.known == 1 and team.exposed_count >= 1
---
# The map outweighs the counter

A countered pick that wins on this map still plays, because the map decides more of a matchup than the counter lists do. Some maps are better than others for each tank yet a matchup low ranks call a hard counter is playable anyway, and a swap forced by a counter was harder than it had to be because the map heavily favoured the countering tank. Measured as the mean win rate of our picks on this map, read while a map is set and at least one of our picks is answered.
