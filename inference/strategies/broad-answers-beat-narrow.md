---
name: Broad answers beat narrow ones
kind: heuristic
category: matchup
metric: team.answer_edges
direction: maximize
weight: 1
when: enemy.size >= 3
---
# Broad answers beat narrow ones

A pick that answers several of red's heroes is worth more than one that answers one, and a six built of broad answers holds up when red swaps. Orisa is named the go-to counter for Reinhardt, Ramattra, Mauga and Doomfist at once, while some heroes counter none. Measured as the total of counter edges from our picks onto revealed red picks, once three or more are revealed.
