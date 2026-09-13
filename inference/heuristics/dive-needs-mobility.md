---
name: A dive comp needs to arrive together
kind: strategy
category: shape
when: map.style_top == 'dive' or team.style_lean == 'dive'
bonus: min(team.mobility_count, 4) * 0.5
---
# A dive comp needs to arrive together

On a map that rewards dive, or when the picks already lean dive, every
pick with a movement tool is one who arrives with the engage instead of
watching it from the choke. Four rewarded; the fifth is the anchor.
