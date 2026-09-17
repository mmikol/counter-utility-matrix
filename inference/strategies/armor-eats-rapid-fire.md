---
name: Armor eats rapid fire
kind: heuristic
category: matchup
metric: team.armor_share
direction: maximize
weight: 1
when: enemy.hitscan >= 3
---
# Armor eats rapid fire

When red fields three or more hitscan picks, the share of our pool that is armor is the share of their fire that never lands whole. Rapid-fire hitscan deals many small instances and armor takes 7 off each up to half, which is why a Soldier: 76 cannot kill through GOATS and why Mauga's miniguns lose half their damage into Orisa before her armor is gone. Armor as a share of the six's pool is measured, read while red fields three or more hitscan picks.
