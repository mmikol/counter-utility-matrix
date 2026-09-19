---
name: Lean the way the map leans
kind: constraint
category: map
when: map.known >= 1 and team.style_lean != '' and team.style_lean != map.style_top
penalty: params.MISMATCH_PENALTY
params:
  MISMATCH_PENALTY: 1
---

# Lean the way the map leans

A comp committed to a style the map does not reward pays for it every fight. Damage supports and snipers thrive where poke dominates and peel is cheap, and die where a brawl map lets red walk onto them. The penalty lands when the picks' majority style differs from the map's rewarded style.
