---
name: Dive runs on cooldowns
kind: heuristic
category: tempo
metric: team.cooldown_median
direction: minimize
weight: 1
when: team.style_lean == 'dive'
---
# Dive runs on cooldowns

A dive six is only as dangerous as its next cooldown, since every engage and every exit is an ability with a timer. Short cooldowns give a diver a second commit before red regains its composure, while long ones leave the six standing in the open waiting to go again. Measured as the median cooldown across every ability on the team, read only while dive is the majority style.
