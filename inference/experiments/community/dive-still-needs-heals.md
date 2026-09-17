---
name: Dive still needs forward healing
kind: heuristic
category: shape
metric: team.hps_floor
direction: maximize
weight: 1
when: team.style_lean == 'dive'
---
# Dive still needs forward healing

A dive comp that stacks mobile supports with thin healing leaves its divers to trade on health packs. The engage lands with the tanks at the front, so the healing has to travel forward with them or the commit is a feed. Measured as summed published healing per second, read only while dive is the majority style.
