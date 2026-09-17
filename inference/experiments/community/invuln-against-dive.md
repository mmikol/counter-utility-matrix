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

A diver's burst is timed to land inside one cooldown window, and an invulnerability on the target wastes it: Suzu dodges 120 damage with one press, Immortality Field holds the backline through the commit, and the diver leaves with nothing. The dive's own play is to bait those cooldowns first, which is a measure of how much they cost it. Measured as the count of picks with an invulnerability, read while 4 or more red picks carry a movement tool.
