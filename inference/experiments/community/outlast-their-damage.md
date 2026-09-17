---
name: Outlast their damage
kind: heuristic
category: durability
metric: matchup.chew_time_theirs
direction: maximize
weight: 1
when: matchup.chew_time_theirs < 999
---
# Outlast their damage

When red's damage floor is high enough that no heal line keeps up, the pool has to absorb it instead. A Bastion and Torbjörn hold or a pocketed hitscan outdamages any two supports, so the comp that survives them is the one whose total hit points take longest to chew through. Seconds of red's floor damage needed to chew our whole pool is measured, higher being longer, read once red has revealed damage.
