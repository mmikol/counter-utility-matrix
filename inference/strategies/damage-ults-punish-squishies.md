---
name: Damage ultimates punish squishies
kind: heuristic
category: damage
metric: team.dmg_ults
direction: maximize
weight: 0.25
when: enemy.squish_count >= 4 and enemy.pool_total <= 1800
---
# Damage ultimates punish squishies

When red seats four or more picks at 250 pool or under and 1,800 total pool or less, every damage ultimate on our side ends a fight outright. One good ultimate wins a fight off a single kill, and a full Earthshatter or Blizzard on a squishy backline is a wipe. Ultimates carrying a damage figure are counted, read while red fields four or more squishies on 1,800 pool or less.
