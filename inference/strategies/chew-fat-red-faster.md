---
name: Chew a fat red faster
kind: heuristic
category: damage
metric: matchup.chew_time_ours
direction: minimize
weight: 0.5
when: enemy.pool_total >= 2000
---
# Chew a fat red faster

When red fields a fat six, the comp that chews through that pool fastest ends its fights before red's ultimates come up. Bastion holds 115 damage per second and Reaper 153, so against 2,000 or more summed hit points steady damage turns a tank line into kills. Measured as the seconds of our floor damage needed to chew red's pool, lower being better, read while red's summed pool is 2,000 or more.
