---
name: Defenders hold ground
kind: constraint
category: side
when: map.side == 'defense'
bonus: min(team.deployables, 2) * 0.5 + min(team.barrier_count, 2) * 0.5 + (0.5 if team.range_median >= 20 else 0)
---
# Defenders hold ground

On the defending side the geometry is yours: deployables (turrets,
walls, lamps) and barriers make a choke expensive to cross, and reach
lets the comp chip the approach before the attackers can commit.

Judged from the kits, like its attacking twin, and weighted the same:
enough to tilt a close call between two comps the heuristics rate alike,
never enough to override coverage or cohesion.
