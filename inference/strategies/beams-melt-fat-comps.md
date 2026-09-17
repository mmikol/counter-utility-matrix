---
name: Beams melt a fat comp
kind: heuristic
category: damage
metric: team.beam
direction: maximize
weight: 1
when: enemy.squish_count <= 2 and enemy.size >= 5
---
# Beams melt a fat comp

A red with at most two squishies among five revealed picks is a wall of tank and armored damage, and beams are what the community reaches for into big slow bodies: Zarya beams a Hazard down, Symmetra melts a Reinhardt walking through her, and a beam ignores D.Va's matrix. A beam never misses a target that size and builds as it holds. Measured as our picks with a beam, read while 5 or more red picks are revealed and at most 2 are squishy.
