---
name: Contest a dive red
kind: constraint
category: matchup
when: matchup.dive_pressure >= 4
penalty: max(0, enemy.size - team.coverage) * params.PER_HEAD
params:
  PER_HEAD: 0.75
---
# Contest a dive red

Against a red with four or more movement tools, every red pick our six cannot answer is a diver who runs the lobby, so an unanswered pick costs more here than against a slower red. When the enemy is on a full dive your job is to switch and contest their tank at the least, and the choice against a good Doomfist or Wrecking Ball is to counter them or watch them run over the whole lobby. Three quarters of a point is taken for every revealed red pick that no pick of ours answers, while red fields four or more movement tools.
