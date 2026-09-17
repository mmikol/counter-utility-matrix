---
name: Out-ult their ultimates
kind: heuristic
category: damage
metric: team.ult_damage_total
direction: maximize
weight: 1
when: matchup.ult_threat >= 600
---
# Out-ult their ultimates

When red carries 600 or more of summed ultimate damage, the fight goes to whoever spends the bigger ultimate first, and a six without damage ultimates of its own is playing catch-up in the economy. Teams that farm ultimates win by pressing Q for full team wipes, and a comp that lacks win conditions is left relying on picks and neutral fights while red's ultimates roll in. Summed maximum damage across our damage ultimates is measured, read while red's summed damage-ultimate ceiling is 600 or more.
