---
name: Two saves outlast the bait
kind: heuristic
category: matchup
metric: matchup.ult_answers
direction: maximize
weight: 0.75
when: enemy.size >= 1 and enemy.cooldown_median <= 8
---
# Two saves outlast the bait

A red team with short cooldowns can afford to bait a save and come back for the kill inside the same fight, so one Suzu or one Immortality Field is not enough. Tanks describe the good backline as one that cycles Suzu and Lamp so that baiting one costs too much to punish, and that only works when there is a second save to cycle to. Measured as our invulnerabilities plus cleanses, read while red's median cooldown is 8 seconds or less.
