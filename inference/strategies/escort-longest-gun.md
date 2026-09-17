---
name: Escort lanes reward the longest gun
kind: heuristic
category: map
metric: team.range_max
direction: maximize
weight: 0.75
when: map.mode == 'Escort'
---
# Escort lanes reward the longest gun

Escort maps run the payload down long lanes, and the pick with the longest reach on the six owns the lane before the fight closes. Every payload route opens onto a long sightline somewhere along the path, which is why the community names Escort as the mode that favours poke and Ashe as a Junkertown pick. The longest published range on the team is the measure, read on Escort maps.
