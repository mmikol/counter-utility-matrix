---
name: Self-sufficient under a dive
kind: heuristic
category: sustain
metric: team.lifelines
direction: maximize
weight: 0.75
when: matchup.dive_pressure >= 4
---

# Self-sufficient under a dive

A dive lands on the supports first, and the picks that heal themselves keep fighting through the seconds the support line is the target. Measured as the count of picks carrying any healing at all, read while 4 or more red picks carry a movement tool.
