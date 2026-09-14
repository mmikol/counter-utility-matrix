# Tuning log

Every change to a strategy's frontmatter, newest last: when, what, why, and who.

- 2026-09-14T16:08Z `optimal-play` added as assumption/assumption (the experiment keeps the ground rule the solver and the session hold every comp to: players play optimally) [claude-code-session]
- 2026-09-14T16:25Z `healing-floor` weight: 1 -> 10 (testing an extreme: healing dominates everything else) [claude-code-session]
- 2026-09-14T16:25Z `heal-ten-times-pool` added as constraint/scored: when=team.size >= 1, bonus=min(team.hps_floor / (10 * max(team.pool_total, 1)), 1) * 10 (the user wants healing pushed to an absurd target to see what the engine does with it) [claude-code-session]
