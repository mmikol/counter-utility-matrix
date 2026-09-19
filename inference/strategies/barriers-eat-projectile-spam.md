---
name: A barrier eats projectile spam
kind: heuristic
category: durability
metric: team.barrier_count
direction: maximize
weight: 0.5
when: enemy.projectile >= 5
---
# A barrier eats projectile spam

Rockets, grenades and arrows are the damage a barrier is best at, because they arrive slowly enough to be blocked and splash on the barrier instead of the backline. Tanks are told to eat the spam against a Pharah or a Junkrat. Measured as the count of picks with a barrier, read while 5 or more red picks carry projectile weapons.
