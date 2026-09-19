---
name: Three supports cannot break a hold
kind: constraint
category: side
when: map.side == 'attack' and team.supports >= 3
penalty: params.THIRD_SUPPORT
params:
  THIRD_SUPPORT: 1
---

# Three supports cannot break a hold

A third support keeps the six alive at the choke and no closer to the point, because a hold is broken by damage. The community calls two tanks and four supports fine on defence and trash at attacking, and says a choke is impossible to break without the damage roster. It charges a flat point, 1 by default, on the attacking side while the six carries 3 or more supports.
