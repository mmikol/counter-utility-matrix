---
name: Damage ultimates punish squishies
kind: heuristic
category: damage
metric: team.dmg_ults
direction: maximize
weight: 1
when: enemy.squish_count >= 3
---
# Damage ultimates punish squishies

When red seats three or more picks at 250 pool or under, every damage ultimate on our side is a button that ends a fight outright. One good ultimate wins a fight off a single kill, and a full Earthshatter or Blizzard on a squishy backline is already a wipe, so a comp stacks fight-winning ultimates against a red that cannot absorb them. Ultimates carrying a damage figure are counted, read while red fields three or more squishies.
