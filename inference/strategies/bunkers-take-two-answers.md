---
name: Bunkers take two answers
kind: heuristic
category: matchup
metric: team.double_covered
direction: maximize
weight: 0.25
when: enemy.mobility_count <= 3 and enemy.barrier_count >= 1
---
# Bunkers take two answers

A red built on sustained damage, Bastion behind a barrier with a turret beside him, is not broken by one counter pick. Without two heroes picked against him the team waits for ults, and the immobile comp still needs its turret destroyed first and its spam heroes flanked. Measured as the count of revealed red picks answered by two or more of ours, while red fields a barrier and three or fewer picks with a movement tool.
