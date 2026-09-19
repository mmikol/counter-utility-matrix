---
name: Answers that survive the ban
kind: heuristic
category: matchup
metric: team.banproof_coverage
direction: maximize
weight: 0.25
when: map.bans == 0
---
# Answers that survive the ban

An answer that hangs on one high-ban hero is removed before the match starts: the only counter to a bunker is Sombra and Sombra is permabanned, and a good Mauga bans Ana. Measured as the red picks still answered when our highest-ban-rate answerer is removed from the count, 0 with none revealed, read before the match's bans are made.
