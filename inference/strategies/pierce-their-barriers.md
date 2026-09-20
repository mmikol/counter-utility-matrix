---
name: Pierce what they hide behind
kind: heuristic
category: matchup
metric: team.pierce_dps
direction: maximize
weight: 0.25
when: matchup.barrier_need >= 1200
---

# Pierce what they hide behind

Against a comp that holds a choke behind barriers, damage that ignores the barrier reaches the supports standing behind it: Winston's Tesla Cannon and Moira's Biotic Orb pass through the shield, Reinhardt's Fire Strike flies through it, and a hammer or flail swings past it. Measured as the summed damage of the picks whose kit ignores barriers, read while red fields 1200 or more barrier health: counting heads instead would buy the rule with whoever happens to carry a flail, when what breaks a bunker is how much damage arrives behind the shield.
