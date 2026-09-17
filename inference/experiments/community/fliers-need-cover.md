---
name: Fliers need hitscan cover
kind: heuristic
category: matchup
metric: team.hitscan
direction: maximize
weight: 1
when: matchup.flyers >= 1
---
# Fliers need hitscan cover

When red fields a hero who flies or hovers, every pick of ours with a hitscan weapon or
ability is one more answer they cannot out-manoeuvre. Flight is tagged from the kit's own
keywords and hitscan from the weapon configs, so this is measured, not judged. It reads
only while a flier is on their side; with none revealed it contributes nothing.
