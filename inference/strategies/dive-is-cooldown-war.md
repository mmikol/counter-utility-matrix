---
name: Dive is a cooldown war
kind: heuristic
category: tempo
metric: matchup.tempo_diff
direction: maximize
weight: 1
when: matchup.dive_pressure >= 4
---
# Dive is a cooldown war

When red brings four or more movement kits, the fight is a cycle of engages and the side whose abilities return first gets to engage again. A Flashbang spent on the Wrecking Ball cannot be spent on the Genji or Tracer coming in behind him, and an Anran who gets to try again every cooldown cycle eventually finds the play that wins her team the fight. Measured as red's median cooldown minus ours, positive when we cycle faster, read while red fields four or more picks with a movement tool.
