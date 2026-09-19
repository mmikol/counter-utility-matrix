---
name: Saves outlast a faster tempo
kind: heuristic
category: tempo
metric: team.invuln
direction: maximize
weight: 0.25
when: enemy.size >= 3 and matchup.tempo_diff <= -2
---

# Saves outlast a faster tempo

A red team that cycles its cooldowns faster than ours spends them in one spike, and an invulnerability wastes the spike. Transcendence, Suzu and Life Grip are how the lower-tempo composition survives the higher-tempo team's play and wins the fight after it, which the OWL analysis found on King's Row. Measured as the count of picks with an invulnerability, read while three or more red picks are revealed and red's median cooldown is shorter than ours by 2 seconds or more.
