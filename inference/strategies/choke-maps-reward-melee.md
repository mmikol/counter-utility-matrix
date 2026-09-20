---
name: Choke maps reward melee
kind: heuristic
category: map
metric: team.melee
direction: maximize
weight: 0.75
when: map.chokes >= 0.5 or map.interiors >= 0.5
---
# Choke maps reward melee

A map of tight chokes and rooms puts the fight in someone's face, where a melee weapon does its full damage and a long gun does not. Reinhardt is the community's brawl tank because he swings his hammer at close quarters. Picks with a melee weapon are counted, read on maps whose chokes or interiors stand 0.5 or more above the ordinary map's.
