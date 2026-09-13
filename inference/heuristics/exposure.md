---
name: Walk into no counter already on the field
kind: goal
category: matchup
direction: minimize
metric: team.exposed_count
weight: 2
when: enemy.size >= 1
---
# Walk into no counter already on the field

How many of our picks a revealed enemy is listed as answering. Answering
two enemies means less when both of them also answer you; this is the
other half of `coverage`, and the pair together is the net matchup the
board shows.
