---
name: Poke holds ground behind barriers
kind: heuristic
category: shape
metric: team.barrier_hp
direction: maximize
weight: 1
when: team.style_lean == 'poke'
---
# Poke holds ground behind barriers

A poke comp holds an angle for the whole poke phase, and barriers are what let it stand in a sightline while it chips. Without barrier health the poke six is forced off its angle by the first burst it takes. Measured as summed barrier health the team fields, read only while poke is the majority style.
