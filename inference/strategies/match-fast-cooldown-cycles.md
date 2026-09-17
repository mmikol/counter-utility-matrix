---
name: Match a fast cooldown cycle
kind: heuristic
category: tempo
metric: team.cooldown_median
direction: minimize
weight: 1
when: enemy.cooldown_median <= 7.5 and enemy.size >= 3
---
# Match a fast cooldown cycle

A red whose median cooldown is 7 seconds or under is back for a second engage before a 12-second answer has returned, and a comp on long timers loses that race. The community notes that short cooldowns are what let damage heroes contest angles, because the pick forced out on a long timer has massive downtime. Measured as the median cooldown across our abilities, kept low while 3 or more red picks are revealed and their median cooldown is 7 and a half seconds or under.
