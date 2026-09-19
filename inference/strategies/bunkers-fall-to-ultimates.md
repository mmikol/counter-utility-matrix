---
name: Bunkers fall to ultimates
kind: heuristic
category: damage
metric: team.ult_damage_total
direction: maximize
weight: 0.25
when: enemy.barrier_count >= 2
---
# Bunkers fall to ultimates

A red with two barriers is beaten by the ultimates that go around or through them, not by shooting the barriers. Dragonstrike and Death Blossom pass through or around a barrier; the summed figure also counts Deadeye and Self-Destruct, which a barrier blocks. Measured as the summed maximum damage across our damage ultimates, read while 2 or more red picks carry a barrier.
