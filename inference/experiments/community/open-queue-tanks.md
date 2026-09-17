---
name: At most two tanks
kind: constraint
category: shape
require: team.tanks <= 2
---
# At most two tanks

The game is 6v6 Open Queue: six picks, any mix of roles, with the one limit the queue
itself enforces - no more than two tanks. The roster holds both teams to it. To search
Role Queue's 2-2-2 instead, tighten this file to
`require: team.tanks == 2 and team.damage == 2 and team.supports == 2`.
