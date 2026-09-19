---
name: Two counters playable, three not
kind: constraint
category: matchup
when: enemy.size >= 1
penalty: max(0, team.exposure_edges - params.TOLERATED * team.exposed_count) * 0.75
weight: 0.5
params:
  TOLERATED: 2
---

# Two counters playable, three not

A pick plays into one or two counters, and every counter past the second on the same pick makes it unplayable. Players say they play well into about two counters but beyond that there is only so much yin to go around, that supposed counters do not work unless they are chained, and that heroes go from amazing to feed when their opponents play two or more counters. Each counter edge beyond two per answered pick costs three quarters of a point, with the tolerance a dial.
