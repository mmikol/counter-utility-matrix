---
name: Outrange them
kind: goal
category: matchup
direction: maximize
metric: matchup.range_diff
weight: 0.75
when: enemy.size >= 1
---
# Outrange them

Our median longest reach minus theirs. Whoever outranges chooses the
fight's opening seconds and forces the approach, and the approach is
where brawls bleed. Positive means we open at distance; negative means
we close fast or trade cover.
