---
name: Two rank swingers, no rate
kind: constraint
category: uncertainty
when: team.rank_sensitive_count >= params.SWINGERS
penalty: 1
params:
  SWINGERS: 2
---
# Two rank swingers, no rate

A six with two picks whose win rates swing across ranks carries a mean that describes no lobby. One such pick is a variance the rest can carry, two is a comp whose whole record depends on who is holding the mouse, because their averaged rates disagree with every tier they were averaged from. It charges a flat point once two or more picks swing 6 or more points across ranks.
