---
name: Two light healers lose fights
kind: constraint
category: sustain
when: team.supports >= 2
penalty: max(0, params.HEAL_MARGIN - team.heal_ratio) * 2
params:
  HEAL_MARGIN: 1.1
---

# Two light healers lose fights

Two supports who both heal lightly cannot hold anyone alive under fire. Lúcio, Mercy, Brigitte and Zenyatta bring utility and a trickle, so one of the two has to be a heavy healer. The support line's summed peak single heal is read against the roster's two-support bench, and every tenth it falls short of 1.1 of that bench is charged 0.2.
