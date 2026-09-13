---
name: One tank, two damage, two supports
kind: constraint
category: shape
require: team.tanks == 1 and team.damage == 2 and team.supports == 2
---
# One tank, two damage, two supports

The shape Competitive Role Queue enforces, and the shape every rate in
META was measured under. A composition that is not 1-2-2 is not
comparable to the numbers the other heuristics lean on, so the solver
does not consider one.

Open Queue allows other shapes. To search them, relax this file - for
example `require: team.supports >= 1 and team.tanks <= 2` - and expect
the solver to return shapes the rates cannot vouch for. The shape flags
on the board (TANKLESS, triple DPS, solo heal) keep naming what such a
comp gives up.
