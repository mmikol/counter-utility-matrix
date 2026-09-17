---
name: Outpool the enemy
kind: heuristic
category: durability
metric: matchup.pool_diff
direction: maximize
weight: 1
when: enemy.size >= 4
---
# Outpool the enemy

A six that fields more effective HP than red survives the opening trade that decides most fights. Tanks control a large share of a team's health pool, and a D.Va at 500 HP keeps fighting through poke that sends a 100 HP Genji back to a health pack, so the side with the bigger sum is the side still standing when the cooldowns come back. Measured as our summed health, shield and armor minus red's, read once red has revealed at least 4 picks so the difference is a real comparison.
