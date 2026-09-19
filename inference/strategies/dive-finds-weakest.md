---
name: A dive finds the weakest pool
kind: heuristic
category: matchup
metric: team.pool_min
direction: maximize
weight: 0.5
when: matchup.style_lean_red == 'dive'
---
# A dive finds the weakest pool

A dive tank sorts the enemy into diveable and not diveable, and the pick it lands on first is the one with the smallest health pool. A 175 HP Tracer or a 225 HP support is a one-commit kill for a Winston and D.Va pair, so the floor of the team's health matters more than its total against a mobile team. Measured as the smallest effective pool on the team, read while a majority of red's picks are dive heroes.
