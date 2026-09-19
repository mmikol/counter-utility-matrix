---
name: Match their synergy
kind: heuristic
category: synergy
metric: team.synergy_edges
direction: maximize
weight: 1
when: enemy.synergy_edges >= 2
---

# Match their synergy

When red's picks are documented partners, a six without partners of its own starts the match behind. A comp built from strong synergistic heroes is what makes a metagame in the first place. Measured as the count of authored synergy pairs among our picks, while red carries two or more authored pairs.
