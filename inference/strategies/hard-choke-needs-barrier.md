---
name: A hard choke needs a barrier
kind: constraint
category: map
when: map.style_top == 'brawl'
bonus: min(team.barrier_hp / params.CHOKE_BARRIER, 1) * params.PER_BARRIER
params:
  PER_BARRIER: 0.75
  CHOKE_BARRIER: 1000
---
# A hard choke needs a barrier

A hard choke is crossed behind a barrier or not at all, and a map whose fights are chokes is a map where one barrier is worth a pick. The community's list of the places a shield is needed is a list of hard chokes, King's Row first point, Eichenwalde third, Havana first and third, and the maps left off it have long sightlines instead. Barrier health earns up to 0.75 points where the map rewards brawl, in full at 1000, and more adds nothing.
