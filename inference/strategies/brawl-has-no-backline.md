---
name: Brawl has no backline
kind: heuristic
category: shape
metric: team.range_max
direction: minimize
weight: 0.5
when: team.style_lean == 'brawl'
---
# Brawl has no backline

A brawl six balls up and walks in together, and the pick whose reach stretches to a sightline behind the ball is the backline a brawl is not supposed to have. Reinhardt with Mercy, Ana and two hitscan is a poke comp with a brawl tank in front of it, and the tank dies alone. Measured as the longest range on the team, read only while brawl is the majority style.
