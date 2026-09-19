---
name: Two counters playable, three not
kind: constraint
category: matchup
when: enemy.size >= 1
penalty: max(0, team.exposure_edges - team.exposed_count - params.FREE) * 0.375
weight: 0.5
params:
  FREE: 1
---

# Two counters playable, three not

A pick plays into one or two counters, and every counter past the second on the same pick makes it unplayable. Players say they play well into about two counters but beyond that there is only so much yin to go around, that supposed counters do not work unless they are chained, and that heroes go from amazing to feed when their opponents play two or more counters. Counters past the first on each pick are summed over the six, one of them is free (a dial), and each other costs 0.375 of a point times the rule's weight (0.5): a pick into three counters pays once, and so do two picks into two each.
