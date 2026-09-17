---
name: A must-ban is not a plan
kind: constraint
category: meta
when: team.max_ban_rate >= params.MAGNET
penalty: 1.5
params:
  MAGNET: 20
---
# A must-ban is not a plan

A pick banned in one lobby in five is absent too often to plan around. Below that line a ban is bad luck, above it a ban is the expectation, so the six pays a flat price for carrying such a pick rather than a sliding one. It applies while the highest ban rate on the six reaches the dial, 20 percent by default.
