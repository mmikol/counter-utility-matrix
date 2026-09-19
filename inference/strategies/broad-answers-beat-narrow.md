---
name: Broad answers beat narrow ones
kind: heuristic
category: matchup
metric: team.answer_edges
direction: maximize
weight: 0.25
when: enemy.size >= 3
---
# Broad answers beat narrow ones

A pick that answers several of red's heroes is worth more than one that answers one, and a six built of broad answers holds up when red swaps. Orisa answers Reinhardt, Ramattra and Doomfist at once, 11 heroes in all, while Sierra answers one. Measured as the total of counter edges from our picks onto revealed red picks, once three or more are revealed.
