---
name: Documented pairs must survive the bans
kind: heuristic
category: meta
metric: team.availability
direction: maximize
weight: 0.75
when: team.synergy_edges >= 1
---

# Documented pairs must survive the bans

A six built on a documented pair loses the pair, not one pick, when the ban screen removes either half. Reinhardt comps rely on specific heroes and are beaten by banning one of the key components, and GOATS could be gimped by banning Brigitte or Lúcio. Measured as the chance every pick survives the ban screen, the product of one minus each pick's ban rate, while the six holds at least one authored pair.
