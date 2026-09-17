---
name: Beams melt on armor
kind: heuristic
category: matchup
metric: team.beam
direction: minimize
weight: 0.5
when: enemy.armor_total >= 300
---
# Beams melt on armor

Armor takes a fixed cut out of every beam tick, so a beam that shreds a 225-pool support does far less to an armored tank. The health-pool thread names beam weapons as the one caveat to how armor works, a flat 30 percent off, and Winston players are told to mix melee into the beam against armor for that reason. Measured as the count of picks with a beam, fewer is better, read while red fields 300 or more armor.
