---
name: Brawl walks in together
kind: heuristic
category: durability
metric: team.pool_min
direction: maximize
weight: 0.75
when: team.style_lean == 'brawl'
---
# Brawl walks in together

A brawl six walks into the fight as one, and its weakest pick walks in too. A support or damage pick that cannot take damage in its face is the first body on the floor of every brawl, and a comp built around one is not a brawl comp. Measured as the weakest pick's effective health, read only while brawl is the majority style.
