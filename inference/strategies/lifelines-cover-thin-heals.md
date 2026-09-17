---
name: Self-heal covers thin support
kind: heuristic
category: sustain
metric: team.lifelines
direction: maximize
weight: 1
when: team.heal_ratio < 1
---
# Self-heal covers thin support

A six whose supports heal below the roster's bench needs its other picks to carry their own sustain, or the tanks feed while waiting. The CTF guide warns that heal output can be low when tanks have no self-sustain, and the lifeline count is the measure of who does. Measured as the count of picks carrying any healing at all, read while the six's summed healing per second is under the world's heal bench.
