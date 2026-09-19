---
name: Sustained pressure baits the saves
kind: heuristic
category: damage
metric: matchup.chew_time_ours
direction: minimize
weight: 0.25
when: enemy.invuln >= 2
---

# Sustained pressure baits the saves

A red with two or more picks that carry an escape or immortality tool, Suzu, Fade, Wraith Form or Cryo-Freeze, cannot be killed in one engage, so the fight goes to whoever spends the saves faster than they come back. That takes a damage floor high enough to force a save every time a pick peeks. Measured as the seconds our floor damage needs to chew red's pool, kept low while 2 or more red picks carry an invulnerability.
