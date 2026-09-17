---
name: Big saves for big hits
kind: heuristic
category: sustain
metric: team.heal_peak_max
direction: maximize
weight: 1
when: enemy.burst_max >= 500
---
# Big saves for big hits

When red carries a 500-damage hit, the only heal that matters is the one large enough to bring a target back from the edge in one press. A Baptiste or Ana line is picked into high burst because a burst heal undoes a rocket volley that a beam would only chase, and Lifeweaver paired with a weak burst healer like Mercy or Brigitte is a nightmare into a bursty red. The biggest single heal on the six is measured, read while red's biggest single hit is 500 or more.
