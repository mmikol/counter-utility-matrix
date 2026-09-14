---
name: Have an answer to their all-in
kind: constraint
category: matchup
when: matchup.ult_threat >= params.THREAT
bonus: min(matchup.ult_answers, 2) * 0.75
params:
  THREAT: 300
---
# Have an answer to their all-in

When the enemy's damage ultimates stack past the threshold, an
invulnerability or a cleanse (lamp, suzu, the transcendence of a
support) is the difference between losing a fight and losing a fight
plus the next one. Two answers rewarded.
