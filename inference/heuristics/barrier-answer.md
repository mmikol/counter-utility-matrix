---
name: Bring barrier-piercers when they wall up
kind: strategy
category: matchup
when: matchup.barrier_need >= params.BARRIER_HP
bonus: min(team.barrier_piercers, 2) * 1.0
params:
  BARRIER_HP: 600
---
# Bring barrier-piercers when they wall up

When the enemy fields serious barrier health, picks whose kit ignores
barriers (the wiki's `ignores_barrier` flag and keywords) restore the
damage math. Up to two are rewarded; a third is redundancy the goals
already price.
