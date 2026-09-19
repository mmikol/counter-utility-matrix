---
name: Outrange them
kind: heuristic
category: matchup
metric: matchup.range_diff
direction: maximize
weight: 0.25
when: enemy.size >= 1
---

# Outrange them

Whoever outranges the other chooses when the fight starts and takes free damage during the approach. Reinhardt has one of the lowest effective ranges in the game and is behind everyone until the gap is closed, and Ashe loses to a Widowmaker at range because falloff decides the duel before aim does. Measured as our median longest reach minus red's.
