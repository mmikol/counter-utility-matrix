---
name: Attackers need ultimates back fast
kind: heuristic
category: tempo
metric: team.ult_cost_mean
direction: minimize
weight: 0.5
when: map.side == 'attack'
---
# Attackers need ultimates back fast

The attacking side spends its ultimates on every push and needs them back before the next one, so the six whose ultimates charge cheaply pushes with them more often. The community reads attackers as blowing ults each time the defence sets up and as having them again on the second or third push. The mean ultimate charge cost across the six is the measure, minimised on the attacking side.
