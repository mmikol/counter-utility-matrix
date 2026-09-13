---
name: Shut off a heavy heal line
kind: constraint
category: matchup
when: enemy.heal_ratio >= params.HEAL_RATIO
bonus: min(team.antiheal, 1) * 1.5
params:
  HEAL_RATIO: 1.0
---
# Shut off a heavy heal line

When their support line heals at or above the roster bench, one
anti-heal pick (a negative healing modifier in the kit - the grenade,
the discord of healing) is worth more than another damage dealer. One
is rewarded; two overlap.
