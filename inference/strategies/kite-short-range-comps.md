---
name: Kite a short-range comp
kind: heuristic
category: matchup
metric: team.range_median
direction: maximize
weight: 0.5
when: enemy.range_max <= 60 and enemy.size >= 5
---
# Kite a short-range comp

A red whose longest gun stops at 60 metres has to walk into our fire to deal any, so every extra metre of reach on our side is damage they take for free before the fight starts. Reinhardt has one of the lowest effective ranges in the game and everyone who outranges him holds the advantage until the gap is closed. Measured as the median of each pick's longest range, read while 5 or more red picks are revealed and none reaches past 60 metres.
