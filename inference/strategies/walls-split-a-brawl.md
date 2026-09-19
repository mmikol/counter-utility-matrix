---
name: Walls split a brawl
kind: heuristic
category: matchup
metric: team.deployables
direction: maximize
weight: 0.75
when: matchup.style_lean_red == 'brawl'
---

# Walls split a brawl

A brawl team is dangerous only together, and a deployable wall or barrier splits it. The pro Mei guide's uses for the wall are placing it in front of the enemy brawl comp and cutting one pick off from their team, and the OWL analysis reads Reinhardt's barrier and Mei's wall as the same tool for splitting line of sight. Measured as the count of picks with deployables, read while red's majority playstyle is brawl.
