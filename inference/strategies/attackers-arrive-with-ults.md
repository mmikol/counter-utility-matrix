---
name: Attackers arrive with ultimates
kind: heuristic
category: side
metric: team.ult_damage_total
direction: maximize
weight: 1
when: map.side == 'attack'
---
# Attackers arrive with ultimates

Attackers need one won fight to take the point and they choose when to take it, so they arrive with the ultimates the defence has to answer. The community expects the attackers to have ults on the second or third push and to blow them each time the defence sets up. The summed maximum damage across the team's damage ultimates is the measure, read on the attacking side.
