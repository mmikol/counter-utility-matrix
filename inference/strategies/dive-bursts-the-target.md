---
name: Dive bursts its target
kind: heuristic
category: damage
metric: team.burst_max
direction: maximize
weight: 1
when: team.style_lean == 'dive'
---
# Dive bursts its target

A dive six kills inside the window its cooldowns buy, so it needs one hit big enough to finish what it lands on. Divers arrive on a target from several angles at once and leave when the movement tools are spent, and a target that survives the collapse walks away healed while the divers sit without cooldowns. Measured as the biggest single damage figure on the team, read only while dive is the majority style.
