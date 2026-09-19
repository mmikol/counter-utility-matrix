---
name: A solo tank needs armor
kind: heuristic
category: durability
metric: team.armor_total
direction: maximize
weight: 0.75
when: team.tanks <= 1
---
# A solo tank needs armor

When one tank holds the front alone, the comp needs the armor to stand under focus. Orisa held a solo-tank front through triple damage because she could not be focused down, and armor is the pool type that shrugs off the spam a lone front line eats. The summed armor across the six is read, only while the six carries at most one tank.
