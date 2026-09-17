---
name: Brawl has no vertical answer
kind: constraint
category: map
when: map.style_top == 'dive' and team.style_lean == 'brawl'
penalty: params.BRAWL_ON_DIVE
params:
  BRAWL_ON_DIVE: 1
---
# Brawl has no vertical answer

A comp that leans brawl is stuck on the low ground of a map built around verticality. Brawl mobility runs along the floor, a charge or a speed boost, and none of it climbs, so the high ground stays with whoever took it first. The penalty lands when a strict majority of the six carry the brawl tag on a map whose rewarded style is dive.
