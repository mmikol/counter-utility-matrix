---
name: A coin-flip lineup is no plan
kind: constraint
category: meta
when: team.availability < params.COINFLIP
penalty: 1.5
params:
  COINFLIP: 0.5
---
# A coin-flip lineup is no plan

A six that reaches the match intact less than half the time is a plan for some other lobby. Two ban magnets on one six multiply their odds against each other, so even moderate ban rates stack into a lineup that usually loses a piece at the ban screen. It charges a flat point and a half while the chance every pick survives the ban screen is under the dial, one half by default.
