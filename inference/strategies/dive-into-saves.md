---
name: Saves blunt a full dive
kind: constraint
category: matchup
when: team.style_lean == 'dive' and enemy.invuln + enemy.cleanse >= params.SAVES
penalty: min(enemy.invuln + enemy.cleanse, 4) * 0.5
params:
  SAVES: 2
---
# Saves blunt a full dive

A dive six that commits into a backline holding immortality, cleanse and defensive ultimates burns its cooldowns and dies in the open. Each save on red is one full dive that lands on nothing, so the more of them red fields the more a dive lean costs. The penalty lands while dive is the majority style and red holds 2 or more invulnerabilities and cleanses, half a point per save up to 4.
