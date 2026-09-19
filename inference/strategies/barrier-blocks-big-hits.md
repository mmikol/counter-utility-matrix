---
name: A barrier blocks the big hit
kind: heuristic
category: durability
metric: team.barrier_count
direction: maximize
weight: 0.25
when: enemy.one_shots >= 1 and enemy.burst_ranged >= 300
---
# A barrier blocks the big hit

When red carries a ranged hit of 300 or more, a Widowmaker headshot, no heal arrives in time and the only answer is something that takes the hit instead of a player. Measured as our picks with a barrier, read while red fields a one-shot pick and its biggest single hit from a pick that is not melee-only is 300 or more.
