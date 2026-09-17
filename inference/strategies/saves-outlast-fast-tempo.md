---
name: Saves outlast a faster tempo
kind: heuristic
category: tempo
metric: team.invuln
direction: maximize
weight: 1
when: enemy.size >= 1 and matchup.tempo_diff < 0
---
# Saves outlast a faster tempo

A red team that cycles its cooldowns faster than ours spends them in one spike, and an invulnerability wastes the spike. Sound Barrier, Transcendence and Suzu are how the lower-tempo composition survives the higher-tempo team's play and wins the fight after it, which the OWL analysis found on King's Row fight after fight. Measured as the count of picks with an invulnerability, read while red's median cooldown is shorter than ours.
