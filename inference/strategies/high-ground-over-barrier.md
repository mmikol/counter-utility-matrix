---
name: High ground looks over a barrier
kind: constraint
category: map
when: map.high_ground >= 0.5
penalty: min(team.barrier_hp / params.BARRIER_HP, params.BARRIER_CAP) * 0.5
params:
  BARRIER_CAP: 2
  BARRIER_HP: 1000
---
# High ground looks over a barrier

A barrier faces one way and the enemy on the high ground above it shoots past it, so on a map built around high ground a barrier tank is a slow pick paying for a tool that does not work. Reinhardt is named as ineffective on Numbani's first two points for the high ground around them. Each 1000 of barrier health costs half a point where the map's high ground stands 0.5 or more above the ordinary map's, up to 2000.
