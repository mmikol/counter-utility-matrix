---
name: Loners lose the ledger
kind: heuristic
category: matchup
metric: team.net_edges
direction: maximize
weight: 0.75
when: enemy.isolated_count >= 2
---
# Loners lose the ledger

When two or more of red's picks have no documented partner, red plays as individuals, and a six that wins more duels than it loses picks them apart one matchup at a time. Steamrolls come from poor synergy all round, sub-optimal character matchups and not fighting together, and a team that does not synergise is beaten by focusing the members who are easier to isolate and engage. Measured as our counter edges onto red minus red's onto us, while red fields two or more picks with no authored partner.
