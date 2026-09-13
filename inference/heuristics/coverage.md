---
name: Answer every revealed enemy
kind: goal
category: matchup
direction: maximize
metric: team.coverage_share
weight: 3
when: enemy.size >= 1
---
# Answer every revealed enemy

The share of revealed enemies at least one of our picks answers, from
the playbook's counters table. The single strongest lever the database
holds: a comp that answers all five has a plan for every fight, and one
that answers two is hoping the other three misplay.

Weighted highest because, under the optimal-play assumption, unanswered
enemies do not misplay.
