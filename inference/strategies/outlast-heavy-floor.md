---
name: Outlast a heavy floor
kind: heuristic
category: durability
metric: matchup.chew_time_theirs
direction: maximize
weight: 1
when: enemy.dps_floor >= 900
---
# Outlast a heavy floor

Against a red whose published damage floor is 900 or more per second, the comp that takes longest to chew is the one still on the objective when their ammunition and cooldowns run out. A tank line that shrugs off a Bastion needs seconds of life rather than one, and a support line will never outheal that output, so the pool has to buy the time. Measured as the seconds red's floor damage needs to chew our pool, read while red's per-second damage floor is 900 or more.
