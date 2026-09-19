---
name: Self-heal covers thin support
kind: heuristic
category: sustain
metric: team.lifelines
direction: maximize
weight: 0.25
when: team.hps_ratio < 0.7
---

# Self-heal covers thin support

A six whose supports heal below the roster's bench needs its other picks to carry their own sustain. The CTF guide warns that heal output can be low when tanks have no self-sustain. Measured as the count of picks carrying any healing at all, read while the supports' sustained healing is under 0.7 of the roster's two-support bench.
