---
name: Solo healer, main healer
kind: heuristic
category: sustain
metric: team.heal_peak_supports
direction: maximize
weight: 1
when: team.supports == 1
---

# Solo healer, main healer

When one support carries the whole heal line, that support has to be the heavy kind. A light healer alone tops nobody off through focus, which is why Mercy is not a solo healer, while Ana, Baptiste or Kiriko alone can hold the front while the fight is decided. The summed peak single heal across the supports is read, which with one support is that support's own peak, only while exactly one support is on the six.
