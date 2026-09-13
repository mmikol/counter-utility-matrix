---
name: Fliers need a hitscan answer
kind: constraint
category: matchup
when: enemy.flyers >= 1
soft: true
require: team.hitscan >= 1
penalty: 2.5
---
# Fliers need a hitscan answer

When the enemy fields a hero who flies or hovers, a comp with no hitscan
weapon answers them with projectiles and hope. The data layer tags
flight from the kit's own keywords and descriptions, and hitscan from
the weapon configs, so this is measured, not judged.

Soft, because a barrier-and-brawl comp can sometimes deny the ground a
flier's team needs - but that argument has to beat a 2.5-point penalty.
