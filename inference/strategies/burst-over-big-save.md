---
name: Burst over their big save
kind: heuristic
category: damage
metric: matchup.burst_vs_heal
direction: maximize
weight: 1
when: enemy.heal_peak_max >= 250
---
# Burst over their big save

When red carries a single save of 250 or more, the damage that kills is the hit that lands before the save does. Healing a critical target from under 20 percent back over 65 percent undoes any 120-damage rocket, so against a big-heal support the pick that matters is the one whose single hit clears that save outright, which is why nobody heals a Widowmaker headshot. Measured as our biggest single hit minus red's biggest single heal, read while red's biggest single heal is 250 or more.
