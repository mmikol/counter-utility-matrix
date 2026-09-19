---
name: Bigger ball wins the brawl
kind: heuristic
category: durability
metric: matchup.pool_diff
direction: maximize
weight: 0.5
when: team.style_lean == 'brawl' and matchup.style_lean_red == 'brawl'
---
# Bigger ball wins the brawl

When both teams brawl the two balls collide and the one with more health to spend outlasts the other. A tank with enough armor to take the face to face fight but not enough to win it loses the mirror to the one that has more. Measured as our effective health minus red's, read only while both majority playstyles are brawl.
