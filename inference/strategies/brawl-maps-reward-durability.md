---
name: Brawl maps reward durability
kind: heuristic
category: map
metric: team.pool_total
direction: maximize
weight: 1
when: map.style_top == 'brawl'
---
# Brawl maps reward durability

In corridors and chokes the fight is decided by who lasts longer in each other's face. A brawl map gives no room to disengage, so the comp with more health, armor and shield to spend up close wins the scrum. Summed effective hit points across the six is the measure, read on maps whose rewarded style is brawl.
