---
name: Leave nothing diveable
kind: heuristic
category: durability
metric: team.squish_count
direction: minimize
weight: 1
when: matchup.style_lean_red == 'dive'
---

# Leave nothing diveable

A pick at 250 health or under is diveable, and every one on the six is a target red's divers can collapse on inside one set of cooldowns. Measured as picks at or under 250 pool, read only while red's majority playstyle is dive.
