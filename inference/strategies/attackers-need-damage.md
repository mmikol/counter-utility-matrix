---
name: Attackers need damage picks
kind: heuristic
category: shape
metric: team.damage
direction: maximize
weight: 0.75
when: map.side == 'attack'
---
# Attackers need damage picks

A choke does not break under healing, and a six heavy on supports holds the ground it has but cannot take the ground it does not. A choke is impossible to break without the damage roster, so a support-heavy six pays on attack over and above what the shape rules charge it everywhere. Damage picks are counted, read on the attacking side.
