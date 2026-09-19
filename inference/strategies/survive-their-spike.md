---
name: Survive their high-tempo spike
kind: heuristic
category: tempo
metric: team.overhealth_total
direction: maximize
weight: 0.75
when: matchup.tempo_diff >= 2
---

# Survive their high-tempo spike

A comp built on long cooldowns spends them together and is strongest for a few seconds, then weakest until they return, so the team with faster cooldowns wins by living through that spike and striking in the lull. Overhealth absorbs the spike: Sound Barrier, Rally and a Zarya bubble add a pool the burst has to chew through before the real health. Measured as the summed peak overhealth the team's kits can grant, read while red's median cooldown exceeds ours by 2 seconds or more.
