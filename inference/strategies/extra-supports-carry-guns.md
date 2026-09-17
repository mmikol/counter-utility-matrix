---
name: Extra supports carry guns
kind: heuristic
category: damage
metric: team.dps_count
direction: maximize
weight: 1
when: team.supports >= 3
---
# Extra supports carry guns

A six that seats a third support keeps its kill threat only if that support carries a gun with a published damage figure. 2-1-3 works with Zenyatta because his orbs deal real damage and he never stops shooting to heal, while a third healer who only heals gives the fight too much sustain and not enough damage. Picks whose kit publishes a per-second damage figure are counted, read while three or more supports are seated.
