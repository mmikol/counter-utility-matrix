---
name: Two tanks hold the front
kind: constraint
category: shape
when: team.size >= 4
bonus: min(team.tanks, 2) * params.PER_TANK
penalty: ('TANKLESS' in team.shape_flags) * params.PER_TANK
params:
  PER_TANK: 1
---

# Two tanks hold the front

In 6v6 two tanks hold the front and the off angle at once: one takes the space and the other forces the flank away from the backline. A comp with no tank has nobody to walk behind, and one tank alone has to choose between the front and the angle every fight. Scored as one per tank up to two, and one more against a tankless six, once four or more picks are locked.
