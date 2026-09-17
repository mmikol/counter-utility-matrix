---
name: Bans target the counters
kind: constraint
category: matchup
when: team.coverage >= 1
penalty: (team.coverage - team.banproof_coverage) * 0.5
---
# Bans target the counters

Bans remove answers before they remove comps, so every enemy whose only answer is the six's most-banned pick is an answer that vanishes with one vote. A protect-and-ban phase has been seen to reinforce the meta precisely by banning the counters, and the ladder's ban screen does the same by weight of votes. The difference between enemies answered and enemies still answered without the highest-ban answerer is charged, half a point each.
