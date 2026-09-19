---
name: Field two damage picks
kind: constraint
category: shape
when: team.size >= 4
penalty: max(0, params.MIN_DAMAGE - team.damage) * 1.2
weight: 1
params:
  MIN_DAMAGE: 2
---

# Field two damage picks

A six needs at least two damage picks, because damage heroes make the pressure that lets a tank take space and that stops red from pushing. Supports can deal damage but cannot focus it or sustain it through their cooldown gaps the way a damage kit does. The penalty grows by 1.2 per damage pick short of two.
