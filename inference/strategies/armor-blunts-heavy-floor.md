---
name: Armor blunts a heavy floor
kind: heuristic
category: durability
metric: team.armor_total
direction: maximize
weight: 1
when: enemy.dps_floor >= 900
---
# Armor blunts a heavy floor

Against a red whose published damage floor is heavy, armor is the pool that shrinks every incoming hit. Armor takes 7 off each instance of damage up to half of it, so a stream of small hits from Soldier: 76, Tracer or Bastion loses close to half its value into an armored six while the same hits land whole on plain health. Summed armor across the six is measured, read while red's per-second damage floor is 900 or more.
