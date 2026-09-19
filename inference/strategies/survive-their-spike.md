---
name: Survive their high-tempo spike
kind: heuristic
category: tempo
metric: team.overhealth_total
direction: maximize
weight: 0.5
when: enemy.size >= 3 and enemy.cooldown_median >= 9.5
---

# Survive their high-tempo spike

A comp built on long cooldowns spends them together and is strongest for a few seconds, then weakest until they return, so the team with faster cooldowns wins by living through that spike and striking in the lull. Overhealth absorbs the spike: Sound Barrier, Tidal Blast and Commanding Shout add a pool the burst has to chew through before the real health. Measured as the summed peak overhealth the team's kits can grant, read while three or more red picks are revealed and red's median cooldown is 9.5 seconds or more.
