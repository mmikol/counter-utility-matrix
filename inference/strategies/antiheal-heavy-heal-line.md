---
name: Anti-heal a heavy heal line
kind: heuristic
category: matchup
metric: team.antiheal
direction: maximize
weight: 1.5
when: matchup.antiheal_need >= world.heal_bench * 1.25
---
# Anti-heal a heavy heal line

Against a support line that heals well above the roster's bench, a landed anti-heal is an instant fight win: 4 seconds without healing turns a pocketed tank into a kill. Moira, Mauga and a double pocket are all played around Ana's grenade, and no damage pick replaces it. Measured as the count of picks with a negative healing modifier, read while red's supports' summed peak heal is at least 1.25 times the world's heal bench.
