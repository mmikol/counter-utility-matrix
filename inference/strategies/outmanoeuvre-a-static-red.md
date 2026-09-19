---
name: Outmanoeuvre a static red
kind: constraint
category: matchup
when: enemy.size >= 3 and enemy.mobility_count <= 3
bonus: min(team.mobility_count, params.MOBILE_CAP) * 0.5
params:
  MOBILE_CAP: 4
---

# Outmanoeuvre a static red

A red team with few movement tools cannot follow a pick that goes in and out, so mobility on our side is worth more against a bunker than against a dive. The bunker thread's answer to Bastion and Torbjörn is that their comp is immobile and has problems with anything that can leave. Read while at least 3 red picks are revealed and 3 or fewer carry a movement tool, and rewarded per pick of ours with one, four at most.
