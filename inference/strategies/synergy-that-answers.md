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

A documented pair earns its place when the six around it also answers red, because a core built for one matchup collapses when that matchup is gone. A tournament's Sigma comp existed to shut down one tank's dive comps and fell off hard once red stopped fielding that tank, so synergy is rewarded here only while the six answers at least half of red. Each authored pair earns half a point, up to four pairs, while at least half of three or more revealed red picks are answered.
