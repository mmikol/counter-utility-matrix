---
name: Build around the strong pick
kind: constraint
category: synergy
when: team.win_mean >= params.STRONG
bonus: min(team.synergy_edges, params.PAIR_CAP) * 0.5
params:
  STRONG: 50
  PAIR_CAP: 4
---
# Build around the strong pick

A metagame starts from a hero who is winning and then a comp built around that hero with partners, so documented pairs are worth more on a six whose picks already win. Teams pick a hero who seems strong and build around them with synergistic heroes, using Brigitte to keep a strong Zenyatta alive even when she is not the second-strongest support in a vacuum. Each authored pair earns half a point, up to four pairs, while the six's mean ladder win rate is 50 percent or better.
