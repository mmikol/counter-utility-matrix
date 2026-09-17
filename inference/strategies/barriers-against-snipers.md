---
name: Barriers against a sniper
kind: heuristic
category: durability
metric: team.barrier_count
direction: maximize
weight: 1
when: enemy.range_max >= 60
---
# Barriers against a sniper

A sniper on red owns every open crossing until something stands in the sightline, and a barrier is the thing that can stand there. Double barrier into snipers is called the reliable answer, and the Mei wall guide's first use for the wall is to deny an oppressive sightline so the team can cross before the fight. Measured as the count of picks with a barrier, read while red's longest reach is 60 metres or more.
