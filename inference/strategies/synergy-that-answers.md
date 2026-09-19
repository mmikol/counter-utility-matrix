---
name: Synergy that also answers
kind: constraint
category: synergy
when: enemy.size >= 3 and matchup.coverage_share >= 0.5
bonus: min(team.synergy_edges, params.PAIR_CAP) * 0.5
params:
  PAIR_CAP: 4
---

# Synergy that also answers

A documented pair earns its place when the six around it also answers red. A tournament's Sigma comp existed to shut down one tank's dive comps and fell off hard once red stopped fielding that tank. Each authored pair earns half a point, up to four pairs, while at least half of three or more revealed red picks are answered.
