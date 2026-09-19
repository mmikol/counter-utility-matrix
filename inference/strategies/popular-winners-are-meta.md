---
name: Popular winners are the meta
kind: constraint
category: meta
when: team.win_mean >= params.EVEN
bonus: min(team.pick_mass / params.MASS_UNIT, 2) * 0.5
params:
  EVEN: 50.5
  MASS_UNIT: 50
---

# Popular winners are the meta

The meta is what wins and gets picked at once. A winning rate on a deep sample is the ladder's verdict and a winning rate on a shallow one is a rumour, so pick rate is worth counting only once the six is on the winning side of even. While the six's mean win rate is at or above the dial, 50.5 by default, half a point per fifty points of summed pick rate is added, capped at one point.
