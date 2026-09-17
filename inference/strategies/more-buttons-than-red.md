---
name: More buttons than red
kind: heuristic
category: tempo
metric: team.cooldown_count
direction: maximize
weight: 0.75
when: enemy.cooldown_count >= 14
---
# More buttons than red

When red brings a full count of cooldowns, ours has to match it or the trades run dry first. The fight is decided by how many resources we hold the line with against how many red has to break it, and a Wrecking Ball that baits three enemy cooldowns for one of his puts red at a cooldown disadvantage for the whole engagement. Cooldowns counted across every ability on the six are measured, read while red's count is 14 or more.
