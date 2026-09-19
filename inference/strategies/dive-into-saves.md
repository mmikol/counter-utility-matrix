---
name: Saves blunt a full dive
kind: constraint
category: matchup
when: team.style_lean == 'dive' and enemy.invuln >= params.SAVES
penalty: min(enemy.invuln, 4) * 0.5
params:
  SAVES: 2
---
# Saves blunt a full dive

A dive six that commits into a backline holding invulnerabilities burns its cooldowns and dies in the open. Each invulnerability on red is one full dive that lands on nothing, so the more of them red fields the more a dive lean costs. The penalty lands while dive is the majority style and 2 or more red picks hold an invulnerability, half a point per pick up to 4.
