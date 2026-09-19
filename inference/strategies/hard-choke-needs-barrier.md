---
name: A hard choke needs a barrier
kind: constraint
category: map
when: map.style_top == 'brawl'
bonus: min(team.barrier_count, 1) * params.PER_BARRIER
params:
  PER_BARRIER: 0.75
---
# A hard choke needs a barrier

A hard choke is crossed behind a barrier or not at all, and a map whose fights are chokes is a map where one barrier is worth a pick. The community's list of the places a shield is needed is a list of hard chokes, King's Row first point, Eichenwalde third, Havana first and third, and the maps left off it have long sightlines instead. One pick with a barrier earns 0.75 points where the map rewards brawl, and a second adds nothing.
