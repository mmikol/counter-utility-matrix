---
name: Thin map sample, trust the ladder
kind: heuristic
category: uncertainty
metric: team.win_mean
direction: maximize
weight: 0.5
when: map.known == 1 and team.map_pick_mass < 30
---

# Thin map sample, trust the ladder

When the six's map figures rest on few games, the ladder-wide win rate is the number that still means something. A map win rate built from a handful of picks swings with every game, while the all-ranks rate pools every map and every rank into a stable figure. The mean all-ranks win rate is read, only on a known map where the six's summed map pick rate is under 30.
