---
name: Fly over a projectile team
kind: heuristic
category: matchup
metric: team.flyers
direction: maximize
weight: 1
when: enemy.size >= 5 and enemy.hitscan <= 1
---
# Fly over a projectile team

A Pharah or Echo is contested by hitscan and by almost nothing else, so a red with at most one hitscan pick leaves the air uncontested. Reaper and Symmetra cannot touch an aerial pick at all, and Torbjörn's turret is bombed from a range he cannot answer. Measured as the count of picks that fly or hover, read while 5 or more red picks are revealed and at most 1 has a hitscan weapon or ability.
