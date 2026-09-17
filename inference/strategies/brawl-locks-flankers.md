---
name: Brawl locks down flankers
kind: heuristic
category: matchup
metric: team.cc_count
direction: maximize
weight: 1
when: team.style_lean == 'brawl'
---
# Brawl locks down flankers

A brawl six wins by denying a diver's mobility once it lands, so it needs the stuns, sleeps and knockbacks that pin a flanker inside the ball. Without them the brawl walks forward while Tracer and Genji take the backline apart behind it. Measured as picks with crowd control, read only while brawl is the majority style.
