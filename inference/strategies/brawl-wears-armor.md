---
name: Brawl wears armor
kind: heuristic
category: durability
metric: team.armor_total
direction: maximize
weight: 0.25
when: team.style_lean == 'brawl'
---
# Brawl wears armor

A brawl six walks into the enemy's fire and stays there, so it wants the health that fire chews slowest. Armor cuts every small hit at the close range brawl chooses, which is why the tanks that win a face to face fight carry it. Measured as summed armor across the team, read only while brawl is the majority style.
