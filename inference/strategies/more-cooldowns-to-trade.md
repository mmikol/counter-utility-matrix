---
name: More cooldowns to trade
kind: heuristic
category: tempo
metric: team.cooldown_count
direction: maximize
weight: 0.5
when: enemy.cooldown_count >= 15
---
# More cooldowns to trade

A fight against a cooldown-rich red is a trade of buttons, and the side with more of them to spend can bait a Flashbang, a Sleep Dart and a nade and still have its own answers up. The community's advice against a stacked defence is to force cooldowns out of the enemy without forcing your own team's. Measured as the cooldowns counted across our abilities, read while red fields 15 or more.
