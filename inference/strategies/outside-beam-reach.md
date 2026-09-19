---
name: Stay out of beam reach
kind: heuristic
category: matchup
metric: team.range_min
direction: maximize
weight: 0.25
when: enemy.beam >= 2 and enemy.range_median <= 25
---

# Stay out of beam reach

Beams do not miss, but Zarya's, Symmetra's and Moira's reach 12 to 20 metres, so a comp whose shortest gun outranges them never stands inside one. Tanks asking how to fight laser heroes are told to make distance and let the ranged picks kill her. Measured as the shortest longest-range on our team, read while 2 or more red picks carry a beam and red's median reach is 25 m or less.
