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

A dive comp feels countered when the backline it would land on is not diveable, and a pick at 250 health or under is always diveable. Every squishy pick on the six is a target red's divers can collapse on and kill inside one set of cooldowns. Measured as picks at or under 250 pool, read only while red's majority playstyle is dive.
