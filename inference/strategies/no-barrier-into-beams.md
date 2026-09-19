---
name: No barrier into beams
kind: heuristic
category: matchup
metric: team.barrier_count
direction: minimize
weight: 0.5
when: enemy.beam >= 2
---

# No barrier into beams

A barrier helps a beam team: Symmetra charges her beam on it, Zarya's beam passes the matrix, and a Reinhardt holding it up dies faster. The tank thread on beam heroes concludes that Symmetra's whole purpose is being good against shield heroes, and that the shield tank's shield only makes her stronger. Measured as the count of picks with a barrier, fewer is better, read while 2 or more red picks carry a beam.
