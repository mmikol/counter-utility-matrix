---
name: Poke shoots hitscan
kind: heuristic
category: damage
metric: team.hitscan
direction: maximize
weight: 0.75
when: team.style_lean == 'poke'
---
# Poke shoots hitscan

A poke six chips from range, and at range only a hitscan weapon lands reliably. Projectiles are dodged across a long sightline while Ashe and Soldier: 76 connect on the first frame; 13 of the 28 poke heroes are hitscan. Measured as picks with a hitscan weapon or ability, read only while poke is the majority style.
