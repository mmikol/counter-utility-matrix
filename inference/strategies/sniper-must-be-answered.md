---
name: A sniper must be answered
kind: heuristic
category: matchup
metric: team.coverage_share
direction: maximize
weight: 1
when: enemy.range_max >= 100
---

# A sniper must be answered

When red holds a weapon that reaches 100 m or more, the six must carry at least one listed answer: a coordinated dive, a flanker or a sniper of our own. A good sniper shuts down an entire team unless someone is dedicated to pressuring her, and taking her down is a team effort against her mobility, her distance and her team peeling for her. Measured as the share of revealed red picks that at least one of ours answers, while red's longest range is 100 m or more.
