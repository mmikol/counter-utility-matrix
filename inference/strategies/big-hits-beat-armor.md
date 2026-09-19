---
name: Big hits beat armor
kind: heuristic
category: damage
metric: team.burst_max
direction: maximize
weight: 0.5
when: enemy.armor_total >= 400
---
# Big hits beat armor

Against an armored red, one big hit keeps its value where a stream of small ones loses half. Armor removes a flat 7 from each instance of damage up to half of it, so a Hanzo arrow or a Roadhog hook combo lands almost whole on Orisa or D.Va while Reaper's pellets and Mauga's minigun rounds are cut in two. The biggest single damage figure on the six is measured, read while red fields 400 or more summed armor.
