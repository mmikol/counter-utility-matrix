---
name: Heal ten times the pool
kind: constraint
category: sustain
when: team.size >= 1
bonus: min(team.hps_floor / (10 * max(team.pool_total, 1)), 1) * 10
---
# Heal ten times the pool

For testing the engine at an extreme: the team should heal, per second, ten times the health pool it carries - or as far towards that as any six can get. The reward grows with the ratio of the healing floor to ten times the pool and caps at that target; every other consideration is drowned out on purpose.
