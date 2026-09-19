---
name: Damage slots are the counter-pick slots
kind: heuristic
category: matchup
metric: team.answer_edges
direction: maximize
weight: 0.25
when: team.damage >= 3 and enemy.size >= 1
---
# Damage slots are the counter-pick slots

A damage-heavy six is the six with the most counter-pick options, and it should use them. Damage players have the deepest hero pool and the most flexibility at counter picking, so three damage slots that do not answer the revealed enemy waste it. The count of counter edges from our picks onto their revealed picks is read, only while three or more damage picks are on the six and red has revealed a pick.
