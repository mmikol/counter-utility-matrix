---
name: Bench healing into heavy fire
kind: heuristic
category: sustain
metric: team.hps_ratio
direction: maximize
weight: 0.5
when: enemy.dps_floor >= 635
---
# Bench healing into heavy fire

Against a red whose damage floor is heavy, the support line has to heal at or above the roster's bench or the tanks fold under it. Without heals pumped in a pick dies in half a second to the current damage numbers, so into a Roadhog or Reaper floor the pick is Kiriko or Ana over Lucio or Brigitte. Measured as the supports' summed sustained healing over the roster's two-support bench, read while red's per-second damage floor is 635 or more.
