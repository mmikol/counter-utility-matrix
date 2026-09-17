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

When red's picks are documented partners, a six without partners of its own starts the match at a disadvantage, because the coordinated side converts every fight it wins into the next. The enemy team will likely have that synergy, so not having it puts you at a disadvantage, and a comp built from strong synergistic heroes is what makes a metagame in the first place. Measured as the count of authored synergy pairs among our picks, while red carries two or more authored pairs.
