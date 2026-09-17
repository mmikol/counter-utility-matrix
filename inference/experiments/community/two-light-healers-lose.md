---
name: Two light healers lose fights
kind: constraint
category: sustain
when: team.supports >= 2
penalty: max(0, params.HEAL_MARGIN - team.heal_ratio) * 2
params:
  HEAL_MARGIN: 0.9
---
# Two light healers lose fights

Two supports who both heal lightly leave the team unable to hold anyone alive under fire. Lúcio, Mercy, Brigitte and Zenyatta bring utility and a trickle, so a pair drawn from that end of the roster pours everything into one target and still loses it, and one of the two has to be a heavy healer. The support line's summed peak single heal is read against the roster's two-support bench and the shortfall below the margin is charged.
