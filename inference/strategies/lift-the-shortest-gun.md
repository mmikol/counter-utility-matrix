---
name: Lift the shortest gun
kind: heuristic
category: matchup
metric: team.range_min
direction: maximize
weight: 1
when: enemy.range_median >= 30
---
# Lift the shortest gun

When red's typical pick reaches 30 m or more, the pick of ours with the shortest gun spends the fight unable to trade. Reinhardt has one of the lowest effective ranges in the game and everyone who outranges him has the advantage until the gap is closed, and a short kit's protection is drained crossing the distance before the fight starts. The shortest of the picks' longest published ranges is measured, read while red's median reach is 30 m or more.
