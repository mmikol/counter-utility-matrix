---
name: Crowd control halts close fighters
kind: constraint
category: matchup
when: enemy.size >= 1 and enemy.range_median <= 30
bonus: min(team.cc_count, params.CC_CAP) * 0.5
params:
  CC_CAP: 3
---
# Crowd control halts close fighters

A red team whose reach is short has to walk into ours to do anything, and every stun, hinder, whip and hook on the six is one more way to stop the walk. Reinhardt, Mauga, Junker Queen and Roadhog are all listed as countered by crowd control and anti-heal rather than by damage, because the tool lands the moment they commit. Read while red's median reach is 30 metres or less, and rewarded per pick with crowd control, three at most.
