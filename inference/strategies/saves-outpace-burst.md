---
name: Saves must outpace their burst
kind: heuristic
category: sustain
metric: matchup.heal_vs_burst
direction: maximize
weight: 1.5
when: matchup.chew_time_theirs < 999
---
# Saves must outpace their burst

Against a comp that lands big single hits, the heal line needs a single save at least as big, or every pick they focus dies between two heals. Ana's grenade, Kiriko's ofuda and Baptiste's burst undo a hit that a Mercy beam or a Lúcio aura cannot, and that gap decides whether red's opener is a kill. Our biggest single heal minus red's biggest single hit is measured, read once red has revealed damage, and a positive margin means their burst is survivable.
