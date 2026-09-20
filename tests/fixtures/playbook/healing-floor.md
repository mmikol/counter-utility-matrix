---
name: Bring sustained healing
kind: heuristic
category: sustain
direction: maximize
metric: team.hps_floor
weight: 1
---
# Bring sustained healing

The six's sustained healing onto teammates, hp per second, reloads in. The `under-healed` constraint handles the cliff (two
supports who together heal little); this heuristic rewards the slope.
