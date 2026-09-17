---
name: Short reach fails on poke maps
kind: heuristic
category: map
metric: team.range_min
direction: maximize
weight: 1
when: map.style_top == 'poke'
---
# Short reach fails on poke maps

On a poke map the pick with the shortest reach is the one who spends the fight unable to shoot back. Beams and shotguns that own a corridor are helpless across a canyon, so a comp is judged there by its shortest longest-range, not its longest. The smallest of the picks' longest published ranges is the measure, read on maps whose rewarded style is poke.
