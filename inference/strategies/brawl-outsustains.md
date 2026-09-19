---
name: Brawl wins by outlasting
kind: heuristic
category: shape
metric: team.hps_floor
direction: maximize
weight: 0.25
when: team.style_lean == 'brawl'
---
# Brawl wins by outlasting

A brawl comp wins the scrum by healing through it: the six ball up at melee range and outlast whatever walks in. Without heavy area healing inside the fight the brawl loses at the close range it chose. Measured as summed published healing per second, read only while brawl is the majority style.
