---
name: One pick cannot answer a core
kind: heuristic
category: matchup
metric: team.double_covered
direction: maximize
weight: 0.75
when: enemy.core_size >= 3
---
# One pick cannot answer a core

Against a red whose picks are documented partners, no single hero counters three others, so the six needs its answers doubled up across several picks. Teams that play together and synergise take several picks to counter, and a tournament's signature comp was met by teams running several counters to one-up it. Measured as the count of revealed red picks answered by two or more of ours, while red's largest synergy group is three or more.
