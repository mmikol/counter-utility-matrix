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

A red with two barriers is a bunker, and the community's answer to a bunker is not to shoot the barrier but to wait for the ultimates that go around or through it. Death Blossom, Dragonstrike, RIP-Tire and Barrage each carry a damage ceiling that no barrier's health absorbs in the second it lands. Measured as the summed maximum damage across our damage ultimates, read while 2 or more red picks carry a barrier.
