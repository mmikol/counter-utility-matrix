---
name: Brawl outlasts a dive
kind: heuristic
category: matchup
metric: team.pool_total
direction: maximize
weight: 0.5
when: matchup.style_lean_red == 'dive'
---
# Brawl outlasts a dive

Brawl beats dive: a dive comp trades durability for mobility, so a team that groups up with a big health pool and swings back is not killed in the seconds the dive has before its cooldowns end. Reinhardt with Brigitte and Lúcio gives a Winston dive nothing to land on. Measured as the team's summed effective health, read only while red's majority playstyle is dive.
