---
name: Boosted guns two-tap squishies
kind: heuristic
category: durability
metric: team.squish_count
direction: minimize
weight: 0.5
when: enemy.dmg_amp >= 2
---
# Boosted guns two-tap squishies

Two damage amplifiers on red, a Mercy beam, a Discord, a Nano Boost or Baptiste's window, cut the hits needed to kill any pick at 250 or under, and nothing heals a headshot. Against that line the comp wants as few picks at 250 or under as the shape allows. Measured as our picks at or under 250 pool, kept low while 2 or more red picks amplify damage.
