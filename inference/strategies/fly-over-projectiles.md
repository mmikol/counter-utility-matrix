---
name: Fly over a projectile team
kind: heuristic
category: matchup
metric: team.flyers
direction: maximize
weight: 1
when: enemy.hitscan <= 2
---
# Fly over a projectile team

A Pharah or Echo is contested by hitscan and by almost nothing else, so a red team whose hitscan is at most a tank's gun and one rifle leaves the air contestable. Reaper and Symmetra cannot touch an aerial pick at all, and Torbjörn's turret is bombed from a range he cannot answer. Measured as the count of picks that fly or hover, read while red fields at most 2 picks with a hitscan weapon or ability.
