---
name: Win the cooldown war
kind: heuristic
category: tempo
metric: matchup.tempo_diff
direction: maximize
weight: 1
when: matchup.chew_time_theirs < 999
---
# Win the cooldown war

Fights turn on which side has cooldowns left when the other does not. A comp that cycles faster than red comes out of every trade with abilities in hand while theirs are still charging, which is the cooldown advantage a Wrecking Ball baits and a Winston exploits. Red's median cooldown minus ours is measured, positive meaning we cycle faster, read once red has revealed damage.
