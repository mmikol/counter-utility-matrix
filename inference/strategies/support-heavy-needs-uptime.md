---
name: A support-heavy six needs uptime
kind: heuristic
category: tempo
metric: team.cooldown_median
direction: minimize
weight: 1
when: team.supports >= 3
---

# A support-heavy six needs uptime

A six seating three or more supports depends on how fast those supports' abilities return. A support forced off an angle has massive downtime and must play safe until her tools are back. The median cooldown across every ability on the six is measured, lower being faster, read while three or more supports are seated.
