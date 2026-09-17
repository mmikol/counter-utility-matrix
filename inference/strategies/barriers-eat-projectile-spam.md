---
name: A barrier eats projectile spam
kind: heuristic
category: durability
metric: team.barrier_count
direction: maximize
weight: 0.75
when: enemy.projectile >= 4
---
# A barrier eats projectile spam

Rockets, grenades and arrows are the damage a barrier is best at, because they arrive slowly enough to be blocked and splash on the barrier instead of the backline. Tanks are told to eat the spam against a Pharah or a Junkrat, and a Reinhardt's barrier is credited with blocking exactly the cooldowns and burst that a projectile team leans on. Measured as the count of picks with a barrier, read while 4 or more red picks carry projectile weapons.
