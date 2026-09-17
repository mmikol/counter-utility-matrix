---
name: Projectiles land on big bodies
kind: heuristic
category: damage
metric: team.projectile
direction: maximize
weight: 0.75
when: enemy.size >= 4 and enemy.squish_count <= 3
---
# Projectiles land on big bodies

A projectile that is hard to land on a 225-pool target is almost guaranteed on a Bastion, a Torbjörn or a tank, so a red team with few squishies is a red team projectiles hit. The bunker thread names Freja, Sojourn, Echo, Hanzo and Pharah as the picks that do considerable damage there for exactly that reason. Measured as the count of picks whose weapons are projectile, read while at least 4 red picks are revealed and 3 or fewer sit at 250 pool or under.
