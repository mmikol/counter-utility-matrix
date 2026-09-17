---
name: Flankers catch the pick fighting alone
kind: heuristic
category: synergy
metric: team.isolated_count
direction: minimize
weight: 0.75
when: matchup.dive_pressure >= 4
---
# Flankers catch the pick fighting alone

Against a red with four or more movement tools, a pick with no documented partner is the one caught alone and burst down before anyone turns around. A flanker's victim is whoever is caught alone, and the reason lone hitscans cannot answer her is that they cannot burst her down fast enough by themselves. Measured as the count of our picks with no authored partner on the six, kept low while red fields four or more movement tools.
