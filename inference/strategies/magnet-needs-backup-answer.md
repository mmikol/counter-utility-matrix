---
name: A banned answer needs a backup
kind: heuristic
category: meta
metric: team.banproof_coverage
direction: maximize
weight: 1
when: team.max_ban_rate >= 15
---
# A banned answer needs a backup

When the pick that answers red is the one the lobby bans, the six needs a second answer that survives the vote. A good Mauga bans Ana before the match, so a comp whose only anti-heal is the ban magnet has no plan the moment the screen closes, while a comp with a second answerer keeps its coverage. Coverage recomputed without the highest-ban answerer is read, only while the six's highest ban rate reaches 15 percent.
