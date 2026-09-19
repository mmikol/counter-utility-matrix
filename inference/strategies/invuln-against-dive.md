---
name: An invulnerability survives the dive
kind: heuristic
category: matchup
metric: team.invuln
direction: maximize
weight: 0.5
when: matchup.style_lean_red == 'dive'
---
# An invulnerability survives the dive

A diver's burst is timed to land inside one cooldown window, and an invulnerability on the target wastes it: Suzu dodges 120 damage with one press. Measured as the count of picks with an invulnerability, read while red's majority style is dive.
