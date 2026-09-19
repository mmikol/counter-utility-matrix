---
name: A thin map sample is noise
kind: constraint
category: uncertainty
when: map.known == 1 and team.map_pick_mass < params.THIN_MAP_MASS
penalty: 1
params:
  THIN_MAP_MASS: 30
---

# A thin map sample is noise

A map win rate built on a few games is noise, and a six of rarely-picked heroes on this map is a six whose map figures cannot be trusted. Pick rate is the sample behind the win rate. It charges a flat point while the six's summed pick rate on the map is under the dial, 30 by default.
