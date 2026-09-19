---
name: Counter-pick on this map only
kind: constraint
category: map
weight: 1
when: map.known == 1 and enemy.size >= 1 and team.map_offmap == 0
bonus: matchup.coverage_share * params.FIT_ANSWERS
params:
  FIT_ANSWERS: 0.5
---
# Counter-pick on this map only

An answer that runs under its own baseline on this map is a swap into a throw pick, so coverage is worth more once no pick of the six is off-map. The community's example is the tank who swaps to Zarya on Numbani, a map they call bad for her, because red has the D.Va she is said to counter. Coverage share earns up to 0.5 points on a known map once red reveals a pick and no pick of the six runs 2.5 points or more under its own baseline there.
