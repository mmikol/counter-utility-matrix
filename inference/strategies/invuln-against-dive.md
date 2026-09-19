---
name: An invulnerability survives the dive
kind: heuristic
category: matchup
metric: team.invuln
direction: maximize
weight: 0.75
when: matchup.dive_pressure >= 4
---
# An invulnerability survives the dive

A diver's burst is timed to land inside one cooldown window, and an invulnerability on the target wastes it: Suzu dodges 120 damage with one press and Immortality Field holds the backline through the commit. Measured as the count of picks with an invulnerability, read while 4 or more red picks carry a movement tool.
