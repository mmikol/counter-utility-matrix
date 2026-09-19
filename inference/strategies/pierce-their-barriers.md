---
name: Pierce what they hide behind
kind: heuristic
category: matchup
metric: team.barrier_piercers
direction: maximize
weight: 0.25
when: matchup.barrier_need >= 1200
---

# Pierce what they hide behind

Against a comp that holds a choke behind barriers, damage that ignores the barrier reaches the supports standing behind it: Moira's beam passes the shield, a grenade lobbed over it lands on the backline, and Zenyatta's orbs take an angle the barrier does not cover. Measured as the count of picks whose kit ignores barriers, read while red fields 1200 or more barrier health.
