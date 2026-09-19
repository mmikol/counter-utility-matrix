---
name: Dive maps need peel
kind: constraint
category: map
when: map.style_top == 'dive'
bonus: max(min(team.cc_count + team.invuln - params.PEEL_FLOOR, params.PEEL_CAP), 0) * 0.5
weight: 0.5
params:
  PEEL_CAP: 3
  PEEL_FLOOR: 3
---
# Dive maps need peel

On a map whose geometry lets the enemy land on the backline from above, the supports need a tool that makes the landing a mistake. The same six needs barely any peel on Circuit Royal and more than can be provided on Ilios: distance substitutes for peel on a poke map and nothing does on a dive map. Each pick with crowd control or an invulnerability beyond the third earns half a point where the map rewards dive, up to 3 picks.
