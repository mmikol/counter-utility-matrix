---
name: Double hitscan grounds fliers
kind: heuristic
category: matchup
metric: team.flyers
direction: minimize
weight: 1
when: enemy.hitscan >= 2 and enemy.range_median >= 30
---
# Double hitscan grounds fliers

A Pharah or Echo in the air has no cover, so two hitscan picks on a red that fights at range turn flight into a liability and the flier gets swapped off within a fight. A Pharah expects to be shot down once the enemy runs double hitscan. Measured as our picks that fly or hover, kept low while 2 or more red picks have a hitscan weapon and red's median reach is 30 m or more.
