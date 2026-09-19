---
name: Raw strength outlasts counters
kind: heuristic
category: matchup
metric: team.win_mean
direction: maximize
weight: 1
when: enemy.size >= 4
---

# Raw strength outlasts counters

Once red has shown its hand, a hero that wins on the ladder still wins through a bad matchup more often than a counter-pick with a losing record wins through a good one. One-tricks reach the top ranks playing into their counters, because a kit that gets value everywhere keeps most of it against the pick that is supposed to shut it down. The mean all-ranks win rate across the six is read, only once red has revealed four or more picks.
