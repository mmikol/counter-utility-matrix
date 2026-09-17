---
name: Answer the must-ban that slipped through
kind: heuristic
category: meta
metric: team.coverage
direction: maximize
weight: 1
when: enemy.max_ban_rate >= 30
---
# Answer the must-ban that slipped through

When red fields a hero the lobby usually bans, that hero is on the field because the ban went elsewhere, and the six must hold an answer to it rather than hope. A Mauga who arrives when the enemy tank starts losing is answered by the supports swapping to Ana or Zenyatta, and a hero left unbanned while the team bans her counter ends up dominating the lobby. Measured as the count of revealed red picks answered by at least one of ours, while red's highest ban rate is 30 percent or more.
