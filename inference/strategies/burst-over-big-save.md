---
name: Burst over their big save
kind: heuristic
category: damage
metric: matchup.burst_vs_heal
direction: maximize
weight: 0.25
when: enemy.heal_peak_max >= 100
---
# Burst over their big save

When red carries a single heal of 100 or more, the damage that kills is the hit that lands before it. Healing a critical target from under 20 percent back over 65 percent undoes any 120-damage rocket, and nobody heals a Widowmaker headshot. Measured as our biggest single hit minus red's biggest single heal, read while red's biggest single heal is 100 or more.
