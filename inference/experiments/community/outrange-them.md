---
name: Outrange them
kind: heuristic
category: matchup
metric: matchup.range_diff
direction: maximize
weight: 0.75
when: enemy.size >= 1
---
# Outrange them

Whoever outranges the other chooses when the fight starts and takes free damage during the approach, and a Reinhardt with one of the lowest effective ranges in the game is at a disadvantage against everyone until the gap is closed. Ashe loses to a Widowmaker at range for the same reason: falloff decides the duel before aim does. Measured as our median longest reach minus red's.
