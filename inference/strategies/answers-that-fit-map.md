---
name: Counter-pick on this map only
kind: heuristic
category: map
metric: matchup.coverage_share
direction: maximize
weight: 0.75
when: map.known == 1 and enemy.size >= 1
---
# Counter-pick on this map only

An answer that runs under its own baseline on this map is a swap into a throw pick, so coverage is worth more once no pick of the six is off-map. The community's example is the tank who swaps to Zarya on Numbani, where she is bad, because red has the tank she is said to counter. Measured as the share of revealed red picks the six answers, read on a known map once red reveals a pick.
