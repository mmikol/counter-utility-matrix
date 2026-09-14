---
name: Take the picks the playbook lists for this map
kind: heuristic
category: map
direction: maximize
metric: team.map_strategy_hits
weight: 1
when: map.known == 1
---
# Take the picks the playbook lists for this map

How many of the six appear in counterpick.gg's best-maps list for the
selected map. A second opinion on `map-fit` from a source that ranks
rather than counts; alignment with it is a cited argument.
