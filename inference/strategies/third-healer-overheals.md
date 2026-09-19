---
name: A third heavy healer overheals
kind: constraint
category: shape
when: team.supports >= 3 and team.hps_ratio >= params.OVERHEAL
penalty: 0.75
params:
  OVERHEAL: 1.6
---

# A third heavy healer overheals

A third support who is also a heavy healer stacks sustain past what any front line can spend. Two heavy healers already clear the roster's two-support bench, so a third turns the slot a damage pick would have used into healing that tops off targets nobody was pressuring. It charges three quarters of a point while three or more supports are on the six and the support line's sustained healing reaches the dial, 1.6 times the two-support bench by default.
