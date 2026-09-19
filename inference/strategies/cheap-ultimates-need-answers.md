---
name: Cheap ultimates need answers
kind: heuristic
category: sustain
metric: matchup.ult_answers
direction: maximize
weight: 0.5
when: enemy.ult_cost_mean <= 2200 and enemy.size >= 3
---
# Cheap ultimates need answers

A red whose ultimates cost 2,200 charge or less on average fires them a fight sooner than a comp of expensive ones, so the invulnerabilities and cleanses that eat an ultimate get used every fight rather than every other. Kiriko negating half the roster's ultimates is the community's example of what that answer count is worth. Measured as our invulnerabilities plus cleanses, read while 3 or more red picks are revealed and their mean ultimate cost is 2,200 or less.
