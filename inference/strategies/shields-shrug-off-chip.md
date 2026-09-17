---
name: Shields shrug off chip
kind: heuristic
category: durability
metric: team.shield_total
direction: maximize
weight: 0.75
when: enemy.size >= 1 and enemy.burst_max < 400
---
# Shields shrug off chip

When red has no hit big enough to delete a pick outright, shield points are the health that comes back on its own between exchanges. Shields regenerate at 30 per second after 3 seconds out of fire, half the wait of the health passive and stacking with it, so a six of Zarya, Sigma, Zenyatta and Juno walks back to full after every poke that a one-shot would have ended. Summed recharging shields on the six are measured, read while red is revealed and their biggest single hit is under 400.
