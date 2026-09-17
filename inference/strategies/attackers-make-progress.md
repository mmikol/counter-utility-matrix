---
name: Attackers must make progress
kind: heuristic
category: side
metric: matchup.chew_time_ours
direction: minimize
weight: 1
when: map.side == 'attack' and matchup.chew_time_ours < 999
---
# Attackers must make progress

A slow fight that ends even is a loss for the attackers, because only the defence gains from the clock running. Aggression is what pays on Escort attack, and a six that cannot chew through red's pool before the timer does never moves the cart. Seconds of blue's floor damage to chew red's pool is the measure, minimised on the attacking side.
