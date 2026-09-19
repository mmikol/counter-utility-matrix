---
name: Press a thin heal line
kind: constraint
category: damage
when: enemy.hps_floor <= params.THIN_HEAL and enemy.supports >= 2
bonus: max(0, min((team.dps_floor - params.PRESS_FLOOR) / 100, 2)) * 0.5
params:
  THIN_HEAL: 100
  PRESS_FLOOR: 500
---

# Press a thin heal line

Two light healers such as Lúcio and Mercy or Brigitte and Zenyatta cannot keep a team standing under sustained fire, and the community calls that pairing the worst backline to play into high damage. Against such a red our floor damage is the number that converts, because nothing they have heals it back. Rewarded half a unit per 100 of our summed per-second damage past 500, one unit at most, while red has 2 or more supports and their summed sustained healing is at or under 100 per second.
