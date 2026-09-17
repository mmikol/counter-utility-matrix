---
name: Ultimates beat heavy healing
kind: heuristic
category: damage
metric: team.dmg_ults
direction: maximize
weight: 1
when: enemy.hps_floor >= 450
---
# Ultimates beat heavy healing

A red whose summed healing per second passes 450 heals back everything that is not a kill in one swing, so its fights are decided by damage ultimates rather than by trading. The community says too much healing makes most damage get outhealed and that against such sustain only burst and ultimates disincentivise the heal line. Measured as our ultimates that carry a damage figure, read while red's summed per-second healing is 450 or more.
