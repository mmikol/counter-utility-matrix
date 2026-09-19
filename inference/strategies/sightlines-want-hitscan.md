---
name: Sightlines want hitscan
kind: heuristic
category: map
metric: team.hitscan
direction: maximize
weight: 0.75
when: map.style_top == 'poke'
---

# Sightlines want hitscan

Long sightlines belong to hitscan weapons, which land at any distance the map offers while projectiles arc and slow. On a poke map the fight opens at the range where a Soldier: 76, Ashe or Widowmaker is already hitting and a projectile kit is not. Picks with a hitscan weapon or ability are counted, read on maps whose rewarded style is poke.
