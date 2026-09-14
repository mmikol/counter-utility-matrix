---
name: Bring sustained healing
kind: heuristic
category: sustain
direction: maximize
metric: team.hps_floor
weight: 10
---
# Bring sustained healing

The sum of each kit's best published per-second healing figure - beams,
streams, auras. The `under-healed` constraint handles the cliff (two
supports who together heal little); this heuristic rewards the slope.
