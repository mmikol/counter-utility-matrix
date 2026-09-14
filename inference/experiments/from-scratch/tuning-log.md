# Tuning log

Every change to a strategy's frontmatter, newest last: when, what, why, and who.

- 2026-09-14T16:08Z `optimal-play` added as assumption/assumption (the experiment keeps the ground rule the solver and the session hold every comp to: players play optimally) [claude-code-session]
- 2026-09-14T16:25Z `healing-floor` weight: 1 -> 10 (testing an extreme: healing dominates everything else) [claude-code-session]
- 2026-09-14T16:25Z `heal-ten-times-pool` added as constraint/scored: when=team.size >= 1, bonus=min(team.hps_floor / (10 * max(team.pool_total, 1)), 1) * 10 (the user wants healing pushed to an absurd target to see what the engine does with it) [claude-code-session]
- 2026-09-14T16:34Z `heal-ten-times-pool` removed (the test it served is done; the user asked for the shape instead) [claude-code-session]
- 2026-09-14T16:34Z `three-damage` added as constraint/limit: require=team.damage == 3 (the user fixes the shape at two tanks, three damage, one support for the experiment) [claude-code-session]
- 2026-09-14T16:34Z `one-support` added as constraint/limit: require=team.supports == 1 (the user fixes the shape at two tanks, three damage, one support for the experiment) [claude-code-session]
- 2026-09-14T16:36Z `three-damage`, `one-support`, `healing-floor`, `optimal-play` removed (back to the two-tank limit alone, on the user's word) [claude-code-session]
- 2026-09-14T18:08Z `fliers-need-cover` added as heuristic/heuristic: metric=team.hitscan, direction=maximize, weight=1, when=matchup.flyers >= 1 (the second rule of the from-scratch playbook: flying requires coverage) [claude-code-session]
- 2026-09-14T18:08Z `healing-covers-the-team` added as heuristic/heuristic: metric=team.hps_floor, direction=maximize, weight=1 (the third rule of the from-scratch playbook: healer coverage) [claude-code-session]
- 2026-09-14T18:44Z `healing-covers-the-team` weight: 1 -> 1.5 (stored from the board's slider) [claude-code-session]
- 2026-09-14T18:48Z `healing-covers-the-team` weight: 1.5 -> 1 (stored from the board's slider) [the board]
- 2026-09-14T18:56Z `healing-covers-the-team` removed (the user asked for it to go: the playbook keeps the two-tank limit and the flier cover, and gains the optimal-play assumption) [claude-code-session]
- 2026-09-14T18:56Z `optimal-play` added as assumption/assumption (the user asked for the assumption that all players play optimally) [claude-code-session]
