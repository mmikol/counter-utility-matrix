---
name: Burst through their saves
kind: heuristic
category: damage
metric: matchup.burst_vs_heal
direction: maximize
weight: 1.5
when: matchup.chew_time_theirs < 999
---
# Burst through their saves

Damage that arrives slower than red's biggest save is healed away, while damage that arrives in one hit larger than that save is a kill. Against a heavy heal line the only shots that count are the ones a Kiriko or an Ana cannot answer, which is why one-shots define fights when healing is strong. Our biggest single hit minus red's biggest single heal is measured, read once red has revealed damage, and a positive margin means their line cannot undo our opener.
