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

Against a red with four or more movement tools, every red pick our six cannot answer is a diver who runs the lobby. The call against a full dive is to contest their tank at the least, and a good Doomfist or Wrecking Ball is either countered or left to run over the whole lobby. Three quarters of a point is taken for every revealed red pick that no pick of ours answers, while red fields four or more movement tools.
