---
name: Press a thin heal line
kind: constraint
category: damage
when: enemy.hps_floor <= params.THIN_HEAL and enemy.supports >= 2
bonus: min(team.dps_floor / params.PRESS_FLOOR, 2) * 0.5
params:
  THIN_HEAL: 320
  PRESS_FLOOR: 500
---
# Press a thin heal line

Two light healers such as Lúcio and Mercy or Brigitte and Zenyatta cannot keep a team standing under sustained fire, and the community calls that pairing the worst backline to play into high damage. Against such a red our floor damage is the number that converts, because nothing they have heals it back. Rewarded per 500 of our summed per-second damage, two units at most, while red has 2 or more supports and their summed healing is at or under the THIN_HEAL dial.
