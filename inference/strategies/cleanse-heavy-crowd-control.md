---
name: Cleanse a crowd-control-heavy red
kind: heuristic
category: matchup
metric: team.cleanse
direction: maximize
weight: 0.5
when: enemy.cc_count >= 5
---
# Cleanse a crowd-control-heavy red

A red team stacked with stuns, sleeps, hinders and knockbacks wins by chaining them onto one target, and a cleanse breaks the chain before the follow-up lands. Kiriko is the community's counterpick into a team with a lot of crowd control, and a second cleanse on the six means the second chain fails too. Measured as the count of picks with a cleanse, read while 5 or more red picks carry crowd control.
