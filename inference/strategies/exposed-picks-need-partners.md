---
name: Countered picks need partners
kind: heuristic
category: synergy
metric: team.synergy_density
direction: maximize
weight: 0.75
when: team.exposed_count >= 3
---
# Countered picks need partners

A six with two or more countered picks needs documented pairs among them, since a counterable hero belongs only in a comp that can peel for it or reduce its vulnerability. Nobody designs a comp that runs a counterable hero beside picks with no reason to cover it, and a Genji who is hard countered by the top picks still works when the comp builds around him. Measured as authored synergy pairs divided by the possible pairs among our picks, while two or more of ours are answered.
