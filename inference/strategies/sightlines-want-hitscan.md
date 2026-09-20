---
name: Sightlines want hitscan
kind: heuristic
category: map
metric: team.hitscan
direction: maximize
weight: 0.75
when: map.sightlines >= 0.5
---

# Sightlines want hitscan

Long sightlines belong to hitscan weapons, which land at any distance the map offers while projectiles arc and slow. On such a map the fight opens at the range where a Soldier: 76, Ashe or Widowmaker is already hitting and a projectile kit is not. Picks with a hitscan weapon or ability are counted, read on maps whose sightlines stand 0.5 or more above the ordinary map's.
