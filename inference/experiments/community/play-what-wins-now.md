---
name: Play what wins right now
kind: heuristic
category: meta
metric: team.win_mean
direction: maximize
weight: 1.5
---
# Play what wins right now

A six of heroes that are winning at the latest capture starts ahead of a six of heroes that are losing. The win rate is the game's own record of which kits are ahead of the current patch, and it holds on every map when nothing else about the board is known. The mean all-ranks win rate across the six is read, in percentage points.
