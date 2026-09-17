---
name: Raise the weakest pool
kind: constraint
category: durability
when: matchup.heal_vs_burst < 0
bonus: min(team.pool_min / params.ONE_SHOT, 2) * 0.5
params:
  ONE_SHOT: 250
---
# Raise the weakest pool

When red's biggest hit is larger than our biggest save, the weakest pool on the six is what focus fire finds first. A 250-pool pick dies to a Widowmaker headshot or a Hanzo arrow before any heal lands, so the picks that survive one hit are the ones still fighting after red's opener. Read only while red's biggest single hit exceeds our biggest single heal, and rewarded per one-shot's worth of the smallest pool on our side, two at most.
