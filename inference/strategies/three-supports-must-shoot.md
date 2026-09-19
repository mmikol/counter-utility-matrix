---
name: Three supports must still shoot
kind: heuristic
category: shape
metric: team.dps_floor
direction: maximize
weight: 1
when: team.supports >= 3
---

# Three supports must still shoot

A comp that fields three or more supports only works when the supports themselves bring the damage the missing damage pick would have. Healing past the point of need adds nothing. Measured as the summed published per-second damage of the six while three or more supports are picked.
