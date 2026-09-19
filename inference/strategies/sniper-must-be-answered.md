---
name: A sniper must be answered
kind: heuristic
category: matchup
metric: team.coverage_share
direction: maximize
weight: 0.25
when: enemy.one_shots >= 1
---

# A sniper must be answered

When red holds a ranged one-shot, the six must carry at least one listed answer: a coordinated dive, a flanker or a sniper of our own. A good sniper shuts down an entire team unless someone is dedicated to pressuring her, and taking her down is a team effort against her mobility, her distance and her team peeling for her. Measured as the share of revealed red picks that at least one of ours answers, while red fields a pick whose ranged hit kills a 250-pool hero.
