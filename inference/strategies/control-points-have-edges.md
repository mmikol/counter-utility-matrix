---
name: Control points have edges
kind: constraint
category: map
when: map.hazards >= 0.5
bonus: min(max(team.cc_count - params.BOOP_FLOOR, 0), params.BOOP_CAP) * 0.5
params:
  BOOP_FLOOR: 2
  BOOP_CAP: 3
---
# Control points have edges

Control stages are built around drops, the well on Ilios, the sanctum pit on Nepal, the edges of Lijiang Tower, and a knockback or a pull turns a full-health enemy into a kill. Roadhog hooking into the well and Lúcio booping on Lighthouse are the community's Control examples, and Orisa is named as good on maps with environmental hazards. Each pick with crowd control beyond the second earns half a point where the map's hazards stand 0.5 or more above the ordinary map's, up to 3 picks.
