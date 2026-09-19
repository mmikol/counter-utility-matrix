---
name: Two light healers lose fights
kind: constraint
category: sustain
when: team.supports >= 2
penalty: max(0, params.HEAL_MARGIN - team.hps_ratio) * 3
params:
  HEAL_MARGIN: 0.7
---

# Two light healers lose fights

Two supports who both heal lightly cannot hold anyone alive under fire. Lúcio, Brigitte, Mizuki and Zenyatta bring utility and a trickle, so one of the two has to be a heavy healer. The support line's summed sustained healing is read against the roster's two-support bench, and every tenth it falls short of 0.7 of that bench is charged 0.3.
