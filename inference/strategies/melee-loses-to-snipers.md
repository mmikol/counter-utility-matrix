---
name: Melee loses to a sniper
kind: heuristic
category: matchup
metric: team.melee
direction: minimize
weight: 0.25
when: enemy.one_shots >= 1
---

# Melee loses to a sniper

A melee pick has one of the shortest effective ranges in the game, and a sniper on red has the advantage every second until the gap is closed. The brawl thread's verdict is that everyone who outranges Reinhardt is ahead of him, and the heavy tanks are countered by long-range poke before anything else. Measured as the count of picks with a melee weapon, fewer is better, read while red fields a pick whose ranged hit kills a 250-pool hero.
