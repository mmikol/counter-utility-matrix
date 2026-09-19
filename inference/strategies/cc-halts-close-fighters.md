---
name: Crowd control halts close fighters
kind: constraint
category: matchup
weight: 0.5
when: enemy.size >= 1 and matchup.style_lean_red == 'brawl'
bonus: max(0, team.cc_count - params.CC_BASE) * 0.5
params:
  CC_BASE: 3
---
# Crowd control halts close fighters

A brawl red has to walk into ours to do anything, and every stun, hinder, whip and hook on the six is one more way to stop the walk. Reinhardt, Mauga, Junker Queen and Roadhog are all listed as countered by crowd control and anti-heal rather than by damage, because the tool lands the moment they commit. Read while a majority of red's picks are brawl heroes, and rewarded 0.25 per pick with crowd control beyond three, 0.75 at most.
