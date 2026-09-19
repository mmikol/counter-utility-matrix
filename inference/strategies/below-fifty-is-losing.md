---
name: Below fifty is losing ground
kind: constraint
category: meta
when: team.win_mean < params.EVEN
penalty: min(params.EVEN - team.win_mean, 4) * 0.5
params:
  EVEN: 49.5
---
# Below fifty is losing ground

A six whose mean win rate sits under fifty is losing on the ladder before the board is read. Every properly ranked player sits at an even record, so a rate below the line says the kit drags its players under, and a six of them compounds it. Each point the six's mean all-ranks win rate falls short of the dial, 49.5 by default, the ladder's pick-weighted mean, costs half a point, capped at four points short.
