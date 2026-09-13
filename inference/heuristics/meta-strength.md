---
name: Prefer what is winning right now
kind: goal
category: meta
direction: maximize
metric: team.win_mean
weight: 1
---
# Prefer what is winning right now

Mean all-ranks win rate across every map at the latest snapshot. A
weak prior next to the map figure, but it is what breaks ties when the
map is unknown or a hero's map sample is thin - and it carries the
snapshot's vintage, so read the WARNING fact when patches shipped since.
