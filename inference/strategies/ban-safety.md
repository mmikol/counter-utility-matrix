---
name: Do not build on a near-certain ban
kind: constraint
category: meta
soft: true
require: team.max_ban_rate < params.BAN_CERTAIN
penalty: 2.5
params:
  BAN_CERTAIN: 35
---
# Do not build on a near-certain ban

A hero banned in more than a third of lobbies is a plan that usually
does not survive the ban screen. Soft rather than hard: when that hero
is the only answer to what the enemy fielded, the rest of the score can
still carry the comp, but it pays for the risk up front.

Pair with `availability`, which prices every pick's ban rate smoothly;
this file is the cliff, that one is the slope.
