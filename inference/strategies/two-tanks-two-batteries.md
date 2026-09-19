---
name: Two tanks are two batteries
kind: heuristic
category: tempo
metric: team.ult_cost_mean
direction: minimize
weight: 0.25
when: enemy.tanks >= 2 and enemy.pool_total >= 1000 + 250 * (enemy.size - 2)
---

# Two tanks are two batteries

Two tanks in front are about 1,000 hit points, half the six's pool, that stand still and take fire, and every hit on them is ultimate charge for the shooter. A comp whose ultimates cost less cashes that charge into a fight-winning ultimate one fight sooner than the enemy does. Measured as the mean charge cost of our ultimates, kept low while red has revealed 2 or more tanks and its summed pool is at least 1,000 plus 250 for each pick past the second.
