---
name: Self-sufficient under a dive
kind: heuristic
category: sustain
metric: team.lifelines
direction: maximize
weight: 0.5
when: matchup.style_lean_red == 'dive'
---

# Self-sufficient under a dive

A dive lands on the supports first, and the picks that heal themselves keep fighting through the seconds the support line is the target. Measured as the count of picks carrying any healing at all, read while red leans dive.
