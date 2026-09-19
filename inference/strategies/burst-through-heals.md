---
name: Burst through their biggest save
kind: heuristic
category: matchup
metric: matchup.burst_vs_heal
direction: maximize
weight: 0.25
when: matchup.antiheal_need >= world.heal_bench
---
# Burst through their biggest save

Healing that brings a pick from low to full in seconds makes chip damage worthless, so a comp facing a strong heal line needs single hits that outsize the biggest save. A Widowmaker headshot or a Hanzo storm arrow volley cannot be healed after the fact. Measured as our biggest single hit minus red's biggest single heal, read while red's support heal peak is at or above the world's heal bench.
