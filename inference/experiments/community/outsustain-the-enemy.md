---
name: Outsustain them in long fights
kind: heuristic
category: sustain
metric: matchup.hps_diff
direction: maximize
weight: 1
when: matchup.chew_time_theirs < 999
---
# Outsustain them in long fights

The comp with the higher healing floor wins any fight that runs long, because whatever damage the other side lands is refilled faster than it is dealt. The side that heals less has to end the fight quickly and is punished for every second it fails to, while the side that heals more wants the fight to drag and gets its wish once the openers are spent. Our summed per-second healing minus red's is measured, read once red has revealed damage.
