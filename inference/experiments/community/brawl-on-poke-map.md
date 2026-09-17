---
name: Brawl cannot close a poke map
kind: constraint
category: map
when: map.style_top == 'poke' and team.style_lean == 'brawl'
penalty: params.BRAWL_ON_POKE
params:
  BRAWL_ON_POKE: 1.5
---
# Brawl cannot close a poke map

A comp that leans brawl loses on a map of long sightlines before it reaches anyone. Brawl kits win once they close the distance and lack the long-range damage to make the crossing cheap, so on open ground the approach is the whole fight and it is lost. The penalty lands when a strict majority of the six carry the brawl tag on a map whose rewarded style is poke.
