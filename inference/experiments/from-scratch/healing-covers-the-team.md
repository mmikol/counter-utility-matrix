---
name: Healing covers the team
kind: heuristic
category: sustain
metric: team.hps_floor
direction: maximize
weight: 1
---
# Healing covers the team

The sum of each pick's best published per-second healing figure - beams, streams, auras - is the healing the team can put out every second of a fight. More of it covers more of the team's health pool under fire, so the solver pushes it up. Nothing here caps how many supports bring it; that is for a later rule, if one is wanted.
