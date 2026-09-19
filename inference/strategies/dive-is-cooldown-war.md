---
name: Dive is a cooldown war
kind: heuristic
category: tempo
metric: matchup.tempo_diff
direction: maximize
weight: 0.5
when: matchup.style_lean_red == 'dive' and matchup.dive_pressure >= 4
---
# Dive is a cooldown war

When red leans dive and brings four or more movement kits, the fight is a cycle of engages and the side whose abilities return first gets to engage again. A Flashbang spent on the Wrecking Ball cannot be spent on the Genji or Tracer coming in behind him, and an Anran who tries again every cooldown cycle eventually finds the play. Measured as red's median cooldown minus ours, positive when we cycle faster, read while dive is red's majority style and four or more red picks have a movement tool.
