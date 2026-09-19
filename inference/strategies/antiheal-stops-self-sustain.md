---
name: Anti-heal turns off self-sustain
kind: heuristic
category: matchup
metric: team.antiheal
direction: maximize
weight: 0.25
when: enemy.lifelines >= 4
---
# Anti-heal turns off self-sustain

When four or more red picks carry healing, the supports included, Mauga's overdrive, Roadhog's breather and Reaper's leech sit on top of the support line, and anti-heal switches all of it off at once. Ana's grenade on a breathing Roadhog or an overdriving Mauga is the standing example. Measured as our picks with anti-heal, read while 4 or more red picks carry any healing.
