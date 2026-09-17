---
name: Map affinity outlasts the patch
kind: heuristic
category: map
metric: team.map_specialists
direction: maximize
weight: 1
when: map.known == 1 and team.win_mean < 50
---
# Map affinity outlasts the patch

A six that is losing on the ladder can still be the right six on this map, because a kit's fit for the ground survives the balance state that dragged its overall rate down. A nerfed hero at 43 percent overall that still pulls 49 percent on Dorado has structural synergy with Dorado, and that is the number to trust when its ladder rate says to leave it home. The count of picks running 2.5 points or more over their own baseline here is read, only on a known map where the six's mean all-ranks win rate is under 50.
