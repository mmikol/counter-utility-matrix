---
name: One support cannot hold a six
kind: constraint
category: shape
when: 'solo heal' in team.shape_flags or 'NO SUPPORT' in team.shape_flags
penalty: max(0, 2 - team.supports) * params.PER_MISSING
params:
  PER_MISSING: 2
---
# One support cannot hold a six

A single support cannot heal six picks through a fight, and red focuses that support first because the whole comp's sustain dies with them. No support at all is worse still, since nothing recovers between engagements. The penalty grows by two per support short of two.
