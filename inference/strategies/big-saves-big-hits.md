---
name: Big saves for big hits
kind: heuristic
category: sustain
metric: team.heal_peak_max
direction: maximize
weight: 0.5
when: enemy.burst_max >= 300
---
# Big saves for big hits

When red carries a 300-damage hit, the heal that matters is the one large enough to bring a target back from the edge in one press. A Baptiste or Ana line is picked into high burst because a burst heal undoes a hit that a beam only chases, and Lifeweaver with Brigitte is two weak burst heals into a bursty red. The biggest single heal on the six is measured, read while red's biggest single hit is 300 or more.
