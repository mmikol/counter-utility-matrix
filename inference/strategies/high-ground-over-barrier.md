---
name: High ground looks over a barrier
kind: constraint
category: map
when: map.style_top == 'dive'
penalty: min(team.barrier_count, params.BARRIER_CAP) * 0.5
params:
  BARRIER_CAP: 2
---
# High ground looks over a barrier

A barrier faces one way and the enemy on the high ground above it shoots past it, so on a map built around high ground a barrier tank is a slow pick paying for a tool that does not work. Reinhardt and Orisa are named as ineffective on Numbani's first two points because there is so much high ground around the point, and without dive the enemy simply jumps back up to it. Each pick with a barrier costs half a point where the map rewards dive, up to 2 picks.
