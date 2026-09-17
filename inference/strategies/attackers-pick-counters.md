---
name: Attackers pick the counters
kind: heuristic
category: side
metric: matchup.coverage_share
direction: maximize
weight: 0.75
when: map.side == 'attack' and enemy.size >= 1
---
# Attackers pick the counters

The attacking side sees the defence set up and walks out of spawn with the answers, while the defenders cannot swap without giving up the ground they hold. The community names this as why a first point falls at once to hard counters and why rock-paper-scissors is horrible for defenders. The share of revealed enemies at least one pick answers is the measure, read on the attacking side.
