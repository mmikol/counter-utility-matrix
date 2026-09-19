---
name: Outdamage a heavy heal line
kind: heuristic
category: damage
metric: matchup.dps_diff
direction: maximize
weight: 0.25
when: enemy.hps_floor >= 235
---

# Outdamage a heavy heal line

When red's supports heal at a heavy per-second rate, only a damage floor that clears theirs by a margin turns their healing into wasted resource. Two damage picks outdamage any amount of healing plus mitigation when they hit, and no support outheals a Bastion alone. Measured as our summed per-second damage minus red's, read while red's summed sustained healing is 235 per second or more.
