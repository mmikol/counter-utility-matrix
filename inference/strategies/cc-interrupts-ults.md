---
name: Crowd control interrupts ultimates
kind: heuristic
category: matchup
metric: team.cc_count
direction: maximize
weight: 0.5
when: matchup.ult_threat >= 1800
---
# Crowd control interrupts ultimates

A channelled or wound-up ultimate dies to a stun or a sleep on the way out: a sleeping Reaper blossoms nobody and Orisa's javelin ends a charge mid-cast. Against a team whose damage ultimates decide fights, one more hard crowd-control tool is one more chance to cancel the play. Measured as the count of picks with crowd control, read while red's damage-ultimate ceiling is 1,800 or more.
