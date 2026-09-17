---
name: Barriers block the burst
kind: constraint
category: durability
when: matchup.heal_vs_burst < 0
bonus: min(team.barrier_count, 2) * 0.75
---
# Barriers block the burst

A barrier is the one kind of sustain that stops a hit before it lands, so against hits too big to heal a comp wants something to hide behind. Reinhardt's and Sigma's barriers eat the shot, the rocket and the ultimate that no heal would have beaten, buying the moment the heal line needs to catch up. Read only while red's biggest single hit exceeds our biggest single heal, and rewarded per barrier pick, two at most.
