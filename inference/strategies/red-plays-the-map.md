---
name: Match red on the map
kind: heuristic
category: map
metric: team.style_fit
direction: maximize
weight: 1
when: enemy.style_fit >= 0.5
---
# Match red on the map

When red has committed to the style the map rewards, every off-style pick of ours meets the map's fight on red's terms. A brawl tank walking out of spawn into full poke on a poke map swaps after the first death or never plays, while a six that matches the map plays the same fight red does. Measured as the share of our picks tagged with the map's rewarded style, read only while at least half of red's picks carry that tag.
