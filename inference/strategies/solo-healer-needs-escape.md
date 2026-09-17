---
name: A solo healer needs an escape
kind: heuristic
category: sustain
metric: team.mobility_count
direction: maximize
weight: 0.75
when: team.supports <= 1
---
# A solo healer needs an escape

A lone support is the enemy's first target every fight, so the comp around them needs the movement to get them out or to pull the dive off them. Two supports can cover each other's cooldown gaps, one cannot, and a pick that is easy to kill is easiest to kill when nobody else heals. The count of picks with a movement or evasive ability across the six is read, only while the six has at most one support.
