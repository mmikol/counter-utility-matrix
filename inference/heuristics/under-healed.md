---
name: Two supports must actually heal
kind: strategy
category: sustain
when: team.supports >= 2 and team.heal_ratio < params.HEAL_MARGIN
penalty: 2
params:
  HEAL_MARGIN: 0.75
---
# Two supports must actually heal

The support line's summed peak single heal against the roster's
two-support bench (twice the median support's peak). Below the margin
the line is complete and still light - two Zenyattas is a choice, and
this strategy makes the solver pay for it rather than stumble into it.
