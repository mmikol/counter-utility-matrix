---
name: Cycle cooldowns faster than they do
kind: heuristic
category: tempo
metric: matchup.tempo_diff
direction: maximize
weight: 0.75
when: enemy.size >= 1
---
# Cycle cooldowns faster than they do

A team whose abilities return sooner re-engages first: shorter cooldowns are why damage picks hold angles that supports are forced off, and a lower-variance comp strikes while the other side waits for its long cooldowns to replenish. The side that cycles faster sets the fight's frequency. Measured as red's median cooldown minus ours, positive when we cycle faster.
