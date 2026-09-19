---
name: Melee swings through barriers
kind: heuristic
category: matchup
metric: team.melee
direction: maximize
weight: 1
when: enemy.barrier_count >= 2
---

# Melee swings through barriers

A barrier stops bullets and projectiles but not a hammer, a punch or a flail: Reinhardt, Ramattra and Brigitte hit what stands behind a Rein or Sigma barrier. Against a double-barrier red every shooter breaks 1,500 health before touching a player, while the melee picks are already on the backline. Measured as our picks with a melee weapon, read while 2 or more red picks carry a barrier.
