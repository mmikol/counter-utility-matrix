---
name: A solo healer needs lifelines
kind: heuristic
category: sustain
metric: team.lifelines
direction: maximize
weight: 0.75
when: team.supports <= 1
---
# A solo healer needs lifelines

With one support or none, every pick that heals itself or a teammate is a second heal line the comp does not otherwise have. Self-sufficient kits, a tank with a breather or a damage pick with a self-heal, lift a burden from the lone healer that would otherwise decide the fight. The count of picks carrying any healing at all is read, only while the six has at most one support.
