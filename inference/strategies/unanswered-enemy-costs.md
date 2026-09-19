---
name: Every unanswered enemy costs
kind: constraint
category: matchup
when: enemy.size >= 1
penalty: max(0, enemy.size - team.coverage) * 0.5
weight: 0.8
---

# Every unanswered enemy costs

The one agreed reason to swap is an enemy on a hero that needs a counter when the team holds none, an aerial Pharah into Reaper and Symmetra being the stock example. Each revealed enemy that no pick of ours answers is one such gap. Every revealed enemy outside every pick's counter list costs half a point times the rule's weight (0.8, so 0.4).
