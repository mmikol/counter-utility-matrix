---
name: A countered lynchpin sinks the comp
kind: heuristic
category: synergy
metric: team.exposed_count
direction: minimize
weight: 0.25
when: team.exposed_count >= 1
---
# A countered lynchpin sinks the comp

A six built on documented pairs has a lynchpin, and when red answers that pick the pair swaps apart and the plan goes with it. The example is a comp with Mei as the lynchpin pick into a red that hard counters her, so the counter to one pick is the counter to the whole comp. Measured as the count of our picks that at least one revealed red pick answers, kept low while at least one of ours is answered.
