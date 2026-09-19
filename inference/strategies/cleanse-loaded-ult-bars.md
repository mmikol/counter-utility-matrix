---
name: Cleanse a loaded ultimate bar
kind: heuristic
category: sustain
metric: team.team_cleanse
direction: maximize
weight: 0.25
when: matchup.ult_threat >= 1800
---
# Cleanse a loaded ultimate bar

When red's damage ultimates add up to 1,800 or more, the fight that matters is the one where two of them land together, and a cleanse lifts the stun or anti-heal that lands beside them. Kiriko's Suzu is credited with negating half the roster's ultimates for exactly that reason. Measured as our picks with a cleanse that lands on a teammate, read while red's summed ultimate damage is 1,800 or more.
