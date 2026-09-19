---
name: Armor eats hitscan spam
kind: heuristic
category: durability
metric: team.armor_total
direction: maximize
weight: 0.5
when: enemy.hitscan >= 3
---
# Armor eats hitscan spam

Hitscan guns deal their damage as many small instances, and armor takes 7 off every one of them up to half, so a Soldier: 76, Tracer or Bastion line loses a large share of its output into an armored comp. Three or more hitscan picks on red is the case where armor is worth the most. Measured as our summed armor, read while 3 or more red picks have a hitscan weapon.
