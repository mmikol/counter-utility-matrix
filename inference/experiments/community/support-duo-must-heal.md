---
name: Two supports must heal between them
kind: constraint
category: shape
when: team.supports >= 2 and team.heal_ratio < params.HEAL_FLOOR
penalty: params.DUO_PENALTY
params:
  HEAL_FLOOR: 0.75
  DUO_PENALTY: 1.5
---
# Two supports must heal between them

Two supports whose healing is both light leave the tanks with nothing to stand on while they take the front. Utility supports are picked for peel, speed and escapes, and pairing two of them means neither can keep a tank up under fire. The penalty lands when the supports' summed peak heal falls under the floor share of the roster's two-support bench.
