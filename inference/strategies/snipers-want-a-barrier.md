---
name: Snipers want a barrier
kind: heuristic
category: durability
metric: team.barrier_count
direction: maximize
weight: 1
when: enemy.range_max >= 100
---
# Snipers want a barrier

When red carries a gun that reaches 100 metres, every open crossing is a headshot waiting to happen, and the community's stock answer to a Widowmaker is to walk behind a barrier rather than to out-aim her. A barrier pick turns the sightline into a barrier-versus-rifle duel and lets the squishies cross. Measured as our picks with a barrier, read while red's longest range is 100 metres or more.
