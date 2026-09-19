---
name: A solo tank cannot dive
kind: constraint
category: shape
when: team.tanks <= 1 and team.style_lean == 'dive' and team.size >= 4
penalty: 1
---

# A solo tank cannot dive

The dive tank leaves the front to jump the backline, and with no second tank the front is empty the moment they go. It charges a flat point once four or more picks are locked with a dive majority and at most one tank.
