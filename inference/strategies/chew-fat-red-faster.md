---
name: Chew a fat red faster
kind: heuristic
category: damage
metric: matchup.chew_time_ours
direction: minimize
weight: 1
when: enemy.pool_total >= 1900
---
# Chew a fat red faster

When red fields a fat six, the comp that chews through that pool fastest ends its fights before red's ultimates come up. A Bastion at 225 damage per second gives every tank about 2.5 seconds of life under full focus, so against 1,900 or more summed hit points steady damage turns a tank line into kills. Measured as the seconds of our floor damage needed to chew red's pool, lower being better, read while red's summed pool is 1,900 or more.
