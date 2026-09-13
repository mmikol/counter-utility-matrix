---
name: At most two tanks
kind: constraint
category: shape
require: team.tanks <= 2
---
# At most two tanks

The game is 6v6 Open Queue: six picks, any mix of roles, with the one
limit the queue itself enforces - no more than two tanks. That limit is
the only shape constraint the solver applies. Everything else about a
comp's shape (no support, four damage, a single frontline) is scored, not
forbidden: the shape flags on the board name it, `under-healed` and
`squish-limit` charge for it, and the goals decide whether it is worth
the price.

To search Role Queue's 2-2-2 instead, tighten this file to
`require: team.tanks == 2 and team.damage == 2 and team.supports == 2`.
