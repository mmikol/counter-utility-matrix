---
name: Amplify damage into thin healing
kind: heuristic
category: matchup
metric: team.dmg_amp
direction: maximize
weight: 0.5
when: enemy.size >= 5 and enemy.supports >= 1 and enemy.hps_ratio < 0.8
---
# Amplify damage into thin healing

When red's supports heal below the roster's bench, their tanks are outdamaged before they are outhealed. Zenyatta's discord on a tank the enemy cannot heal back ends the tank duel early. Measured as the count of picks that amplify someone's damage, read while red shows 5 or more picks, at least 1 support, and its supports' sustained healing is under 0.8 of the roster's two-support bench.
