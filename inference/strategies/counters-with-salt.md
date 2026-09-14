---
name: Answer their picks, lightly
kind: heuristic
category: matchup
metric: matchup.coverage_share
direction: maximize
weight: 0.5
when: enemy.size >= 1
---
# Answer their picks, lightly

The counter lists say who answers whom, and a comp that answers more of red's picks is better placed - but the lists are crowd-sourced opinion, not measured, so they weigh lightly. The share of red's picks that at least one of ours answers is read from the counters table. Half a point of weight: a tie-breaker between comps the other rules rate alike, never the reason for a pick.
