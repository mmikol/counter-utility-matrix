---
name: A rank-swinging rate is noise
kind: heuristic
category: uncertainty
metric: team.rank_sensitive_count
direction: minimize
weight: 0.75
---
# A rank-swinging rate is noise

A pick whose win rate moves 6 or more points between ranks carries an all-ranks mean that describes no rank at all. Kits that live on one mechanic, a scoped headshot, a hooked target, a pocketed flier, are the ones whose value swings with who is playing, so their averaged rate is the least trustworthy number on the board. The count of picks with a 6-point or larger swing across ranks is read.
