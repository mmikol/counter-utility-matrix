---
name: Cheap ultimates crack bunkers
kind: heuristic
category: tempo
metric: team.ult_cost_mean
direction: minimize
weight: 0.25
when: matchup.barrier_need >= 1200
---
# Cheap ultimates crack bunkers

When red fields 1,200 or more barrier HP the fight waits for ultimates, so the six whose ultimates come around soonest breaks the hold first. A comp of cheap, fast-charging ultimates reaches that moment a fight earlier than one built on expensive ones. Mean published ultimate cost across the six is measured, lower being faster, read while red's barrier HP is 1,200 or more.
