---
name: Ultimates beat heavy healing
kind: heuristic
category: damage
metric: team.ult_damage_total
direction: maximize
weight: 0.25
when: enemy.hps_floor >= 190
---

# Ultimates beat heavy healing

A red whose summed sustained healing per second reaches 190 heals back everything short of a kill in one swing, so its fights are decided by damage ultimates rather than by trading. The community says too much healing makes most damage get outhealed and that against such sustain only burst and ultimates disincentivise the heal line. Measured as the summed maximum damage of our damage ultimates, read while red's summed sustained healing is 190 per second or more.
