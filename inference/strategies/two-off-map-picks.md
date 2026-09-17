---
name: Two off-map picks, wrong comp
kind: constraint
category: map
when: map.known == 1 and team.map_offmap >= params.OFFMAP
penalty: 1
params:
  OFFMAP: 2
---
# Two off-map picks, wrong comp

One pick running under its own baseline on a map is a matchup, two is a comp built for a different map. A kit's affinity for a map's geometry survives patches, so a second pick running 2.5 points or more under its baseline here means the comp is fighting the ground as well as the enemy. It charges a flat point while two or more picks run under their own baseline on this map.
