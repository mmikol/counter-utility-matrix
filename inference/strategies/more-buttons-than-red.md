---
name: More buttons than red
kind: heuristic
category: tempo
metric: team.cooldown_count
direction: maximize
weight: 0.5
when: enemy.size >= 3 and enemy.cooldown_count >= 2.8 * enemy.size
---

# More buttons than red

When red brings a full count of cooldowns, ours has to match it or the trades run dry first. A Wrecking Ball who baits three enemy cooldowns for one of his puts red at a cooldown disadvantage for the whole engagement. Cooldowns counted across every ability on the six are measured, read while red averages 2.8 cooldowns a pick or more across three or more revealed.
