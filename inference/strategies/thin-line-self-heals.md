---
name: Self-heals cover a thin line
kind: heuristic
category: sustain
metric: team.heal_peak_total
direction: maximize
weight: 1
when: team.supports <= 1
---
# Self-heals cover a thin line

With one support or none, the healing that keeps the six alive comes from every kit that can heal itself or a neighbour. Baptiste's regen burst makes him 350 effective HP, Ana's grenade heals her for 100, Roadhog breathes and Soldier: 76 drops a field, so a thin support line survives on kits that patch their own bars rather than on the line itself. Summed peak single heal across all picks, any role, is measured, read while the six seats at most one support.
