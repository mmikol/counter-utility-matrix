---
name: Two per role is the baseline
kind: heuristic
category: shape
metric: team.archetype_deviation
direction: minimize
weight: 1.5
when: map.known >= 1
---
# Two per role is the baseline

Two tanks, two damage and two supports is the shape every archetype starts from, and every pick past two in a role is a pick the archetype did not want. Extra supports trade burst for sustain nobody needs, extra damage trades the front line and the healing that keep a fight going. Measured as picks over the role slots of the map's top-style archetype, so it reads only with a map set.
