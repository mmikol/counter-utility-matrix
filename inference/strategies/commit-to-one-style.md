---
name: Half a comp each way fails
kind: constraint
category: shape
when: team.size >= 4 and team.style_lean == ''
penalty: params.HYBRID_PENALTY
params:
  HYBRID_PENALTY: 1.5
---
# Half a comp each way fails

A six with no majority playstyle fights as two half-teams. A brawl tank in front of a poke backline cannot peel what is dove and cannot swing on what is far away, so nobody's kit is used at its range. The penalty lands whenever no style is carried by a strict majority of the picks.
