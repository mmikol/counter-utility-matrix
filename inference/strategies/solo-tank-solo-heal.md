---
name: Solo tank plus solo heal throws
kind: constraint
category: shape
when: team.tanks <= 1 and team.supports <= 1 and team.size >= 4
penalty: 2
---
# Solo tank plus solo heal throws

A six with one tank and one support has already lost its shape, whatever the other four bring. The lone tank cannot hold the front without an off-tank to cover the angle, the lone healer cannot keep that tank and the backline alive at once, and each is the enemy's first target, so the two failures feed each other. It charges two flat points once four or more picks are locked with at most one tank and at most one support.
