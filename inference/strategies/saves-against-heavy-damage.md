---
name: Big saves against heavy damage
kind: heuristic
category: sustain
metric: team.heal_ratio
direction: maximize
weight: 1
when: enemy.dps_floor >= 950
---
# Big saves against heavy damage

No support out-heals a Bastion or a Mauga alone, so against a red whose summed damage floor passes 950 a second the support duo's peak single saves are what keep a pick alive through the burn. A heal line at or above the roster's two-support bench buys the second it takes to reach cover; one below it watches the bar go to zero. Measured as the support heal peak over the roster's two-support bench, read while red's damage floor is 950 or more.
