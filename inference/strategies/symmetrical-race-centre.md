---
name: Symmetrical modes race to the centre
kind: constraint
category: map
when: map.known == 1 and map.sided == 0
bonus: min(team.mobility_count, params.MOBILE_CAP) * 0.25
params:
  MOBILE_CAP: 5
---

# Symmetrical modes race to the centre

On Control, Push and Flashpoint both teams leave spawn at once and the first to the strong positions in the neutral centre holds them. Mobile heroes are called vital in symmetrical modes, Flashpoint is said to punish low mobility outright, and a Push flanker gets back to the team because of mobility. Each pick with a movement or evasive ability earns a quarter point on a symmetrical map, up to 5 picks.
