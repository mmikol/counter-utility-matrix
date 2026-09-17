---
name: One-shots hunt squishies
kind: heuristic
category: durability
metric: team.squish_count
direction: minimize
weight: 1.5
when: enemy.burst_max >= 250
---
# One-shots hunt squishies

When red carries a hit of 250 or more, every pick of ours at 250 pool or under is a target that dies before a heal lands. Widowmaker one-shots the entire non-tank cast and a Sojourn at 225 HP dies instantly to a Wrecking Ball she mispositions against, so the comp into a one-shot red seats fewer picks the hit can delete. Picks at or under 250 pool are counted, fewer being better, read while red's biggest single hit is 250 or more.
