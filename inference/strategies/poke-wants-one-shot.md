---
name: Poke wants a one-shot
kind: heuristic
category: damage
metric: team.burst_ranged
direction: maximize
weight: 0.5
when: team.style_lean == 'poke'
---

# Poke wants a one-shot

A poke six wins the neutral before the fight closes, and the pick that deletes a target across the sightline is what makes the approach cost. Widowmaker's headshot and Hanzo's arrow do that; chip damage that heals back does not. Measured as the biggest single hit from a pick that is not melee-only, a headshot where one counts, read only while poke is the majority style.
