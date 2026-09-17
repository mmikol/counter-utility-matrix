---
name: Stacked counters force a swap
kind: constraint
category: matchup
penalty: max(0, team.exposure_edges - team.exposed_count) * 0.5
---
# Stacked counters force a swap

One counter on a pick is a matchup to play around; a second and a third on the same pick is the enemy team built to delete it, and that is the point where the community says to swap. A Tracer into Cassidy sidesteps the flashbang and keeps farming, but a Tracer into Brigitte, Cassidy, Mercy, Mei and Roadhog kills nobody. Every exposure edge past the first on an already-exposed pick costs half a point, and with no enemy revealed there are no edges.
