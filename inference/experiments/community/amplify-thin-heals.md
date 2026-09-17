---
name: Amplify damage into thin healing
kind: heuristic
category: matchup
metric: team.dmg_amp
direction: maximize
weight: 0.75
when: matchup.antiheal_need < world.heal_bench
---
# Amplify damage into thin healing

When red's supports heal below the roster's bench, their tanks are outdamaged before they are outhealed, and the pick for that board is the amplifier: Zenyatta's discord on a tank the enemy cannot heal back ends the tank duel early. Damage amplification is worth most exactly where there is little healing to fight through. Measured as the count of picks that amplify someone's damage, read while red's support heal peak is under the world's heal bench.
