---
name: Answer the dangerous ones twice
kind: goal
category: matchup
direction: maximize
metric: team.double_covered
weight: 1
when: enemy.size >= 2
---
# Answer the dangerous ones twice

Enemies answered by two or more of our picks. Redundant answers survive
a ban, a swap, or one of ours dying first; single-threaded answers do
not. Worth a point, not three: breadth (`coverage`) comes first.
