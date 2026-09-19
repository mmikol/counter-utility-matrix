---
name: Two tanks are two batteries
kind: heuristic
category: tempo
metric: team.ult_cost_mean
direction: minimize
weight: 0.75
when: enemy.tanks >= 2
---

# Two tanks are two batteries

Two tanks in front are 1,000 or more hit points that stand still and take fire, and every hit on them is ultimate charge for the shooter. A comp whose ultimates cost less cashes that charge into a fight-winning ultimate one fight sooner than the enemy does. Measured as the mean charge cost of our ultimates, kept low while red has revealed 2 or more tanks.
