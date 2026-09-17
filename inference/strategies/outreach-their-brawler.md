---
name: Outreach their brawler
kind: heuristic
category: matchup
metric: team.range_median
direction: maximize
weight: 1
when: enemy.range_min <= 10 and enemy.size >= 1
---
# Outreach their brawler

When red seats a pick whose reach is 10 m or less, a six that fights from further away denies that pick the fight it wants. Reinhardt, Ramattra, Mauga and Roadhog are countered by long-range poke that keeps them out of their effective range, and a brawl's biggest weakness is any situation where it cannot close the distance. The median of each pick's longest published range is measured, read while red is revealed with at least one pick whose longest reach is 10 m or less.
