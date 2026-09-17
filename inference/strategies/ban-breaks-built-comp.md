---
name: A ban breaks a built comp
kind: constraint
category: meta
when: team.max_ban_rate >= params.MAGNET and team.synergy_edges >= 1
penalty: min(team.synergy_edges, params.EDGE_CAP) * 0.5
params:
  MAGNET: 15
  EDGE_CAP: 3
---
# A ban breaks a built comp

A comp that leans on its partners loses more than one pick when its keystone is banned, because every authored pair that ran through that hero goes with it. Rein comps and Sigma-Mizuki comps rely on specific heroes to work, so the more pairs a six has documented, the more one vote against its most-banned pick takes down. While the highest ban rate on the six reaches the dial, 15 percent by default, half a point per synergy pair among the picks is charged, up to three pairs.
