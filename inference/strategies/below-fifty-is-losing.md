---
name: Below fifty is losing ground
kind: constraint
category: meta
when: team.win_mean < params.EVEN
penalty: min(params.EVEN - team.win_mean, 4) * 0.5
params:
  EVEN: 50
---
# Below fifty is losing ground

A six whose mean win rate sits under fifty is losing on the ladder before the board is read. Every properly ranked player sits at an even record, so a hero's rate below the line says the kit itself drags its players under, and a six of such heroes compounds the drag. Each point the six's mean all-ranks win rate falls short of the dial, 50 by default, costs half a point, capped at four points short.
