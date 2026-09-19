---
name: Anti-heal turns off self-sustain
kind: heuristic
category: matchup
metric: team.antiheal
direction: maximize
weight: 0.25
when: enemy.lifelines >= 5
---
# Anti-heal turns off self-sustain

When five or more red picks carry healing of their own, Mauga's overdrive, Roadhog's breather, Bastion's repair and Reaper's leech on top of the supports, anti-heal switches all of it off at once. Ana's grenade on a breathing Roadhog or an overdriving Mauga is the standing example. Measured as our picks with anti-heal, read while 5 or more red picks carry any healing.
