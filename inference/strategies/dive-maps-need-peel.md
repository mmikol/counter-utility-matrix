---
name: Dive maps need peel
kind: constraint
category: map
when: map.style_top == 'dive'
bonus: min(team.cc_count + team.invuln, params.PEEL_CAP) * 0.5
params:
  PEEL_CAP: 2
---
# Dive maps need peel

On a map whose geometry lets the enemy land on the backline from above, the supports need a tool that makes the landing a mistake. The same six needs barely any peel on Circuit Royal and more than can be provided on Ilios: distance substitutes for peel on a poke map and nothing does on a dive map. Each pick with crowd control or an invulnerability earns half a point where the map rewards dive, up to 2 picks.
