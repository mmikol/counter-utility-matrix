---
name: Countered but ahead on the ledger
kind: heuristic
category: matchup
metric: matchup.net_edges
direction: maximize
weight: 0.75
when: team.exposed_count >= 1
---
# Countered but ahead on the ledger

One or two counters on a pick do not force it off when the six is still strong into the rest of red, so an answered pick is judged by the whole ledger rather than by its own matchup. Being countered by two while strong against three is still great value as long as the countered pick does not engage its counters, and a single swap to a counter does not force a swap in higher play. Measured as our answer edges minus red's answer edges onto us, read while at least one of our picks is answered.
