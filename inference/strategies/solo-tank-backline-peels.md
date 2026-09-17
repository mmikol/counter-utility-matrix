---
name: A solo tank's backline peels itself
kind: heuristic
category: shape
metric: team.cc_count
direction: maximize
weight: 1
when: team.tanks <= 1
---
# A solo tank's backline peels itself

With one tank, nobody can leave the front to peel, so the peel has to come from the backline's own kit. In 6v6 the off-tank's job was to turn on the flanker diving the supports, and without one that job falls to a support or damage pick with a stun, a sleep or a knockback. The count of picks with crowd control is read, only while the six carries at most one tank.
