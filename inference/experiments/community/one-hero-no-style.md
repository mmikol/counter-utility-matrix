---
name: One hero is not a style
kind: heuristic
category: map
metric: team.archetype_deviation
direction: minimize
weight: 0.75
when: map.known == 1 and map.style_margin >= 2
---
# One hero is not a style

A single hero of the map's style inside a comp shaped for another does not play that style. Each rewarded style has an archetype of role slots, two tanks who hold or engage, two damage who fight at its range, two supports who survive its commit, and picks stacked past those slots leave the style's plan without the roles it needs. The count of picks over the map's top-style archetype slots is the measure, read where the map's style score reaches 2.
