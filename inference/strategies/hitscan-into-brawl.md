---
name: Hitscan into brawl
kind: heuristic
category: damage
metric: team.hitscan
direction: maximize
weight: 0.75
when: matchup.style_lean_red == 'brawl'
---
# Hitscan into brawl

Against a brawl the hitscan heroes are the answer, because they land the chip damage at the range a brawl cannot answer from. Brawlers walk forward through it, while dive picks would have to land inside the ball where the brawl is strongest. Measured as picks with a hitscan weapon or ability, read only while red's majority playstyle is brawl.
