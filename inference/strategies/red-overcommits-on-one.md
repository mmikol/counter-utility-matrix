---
name: Red overcommits on one pick
kind: heuristic
category: matchup
metric: team.safe_count
direction: maximize
weight: 0.75
when: team.exposure_edges >= 3
---
# Red overcommits on one pick

When red has spent several picks countering one of ours, the rest of our six should be heroes those picks do not answer, because a team geared up to counter one hero has given the other five an easier game. If multiple people have counter-swapped to deal with you that is a win, and a Moira who makes the enemy commit two people just to deal with her is already generating massive value. Measured as the count of our picks that no revealed red pick answers, while three or more counter edges land on the six.
