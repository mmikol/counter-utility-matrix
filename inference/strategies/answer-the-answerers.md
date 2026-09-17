---
name: Answer the ones who answer you
kind: heuristic
category: matchup
metric: team.answer_edges
direction: maximize
weight: 0.75
when: team.exposed_count >= 1
---
# Answer the ones who answer you

When one of our picks is countered, the rest of the six should answer the red picks doing the countering rather than leave that pick to fight its counter alone. A team plays around a counter by making the counter's own pick a target, which is why the advice is to prioritise your tank's counter as an enemy target and to switch to deal with the Zarya instead of banging your head on the wall. Measured as the total of counter edges from our picks onto revealed red picks, read while at least one of ours is answered.
