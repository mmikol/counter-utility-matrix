---
name: Outdamage a heavy heal line
kind: heuristic
category: damage
metric: matchup.dps_diff
direction: maximize
weight: 1.5
when: enemy.hps_floor >= 400
---
# Outdamage a heavy heal line

When red's supports heal at a heavy per-second rate, only a damage floor that clears our own by a margin turns their healing into wasted resource. Two damage picks on a 2-2-2 outdamage any amount of healing plus mitigation when they hit, and no support outheals a Bastion alone, so the fight against a Baptiste and Ana line is won by a floor that exceeds what they can pump back. Measured as our summed per-second damage minus red's, read while red's summed healing floor is 400 or more.
