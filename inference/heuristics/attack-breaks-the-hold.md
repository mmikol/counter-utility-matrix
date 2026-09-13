---
name: Attackers need to break a hold
kind: strategy
category: side
when: map.side == 'attack'
bonus: min(team.mobility_count, 4) * 0.5 + min(team.antiheal, 1) * 0.5
---
# Attackers need to break a hold

On the attacking side of an Escort or Hybrid map the fight starts at a
choke the defenders chose. Engage tools (movement, evasive, flight) let
the comp arrive on the high ground instead of walking into it, and one
anti-heal pick turns a held position into a trade the defenders lose.

The rates do not split by side, so this is a judgement about the kits,
not a measured advantage - which is why it is a strategy with a small
bonus rather than a goal.
