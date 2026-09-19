---
name: Answer the must-ban that slipped through
kind: heuristic
category: meta
metric: team.coverage
direction: maximize
weight: 0.25
when: enemy.max_ban_rate >= 30
---
# Answer the must-ban that slipped through

When red fields a hero the lobby usually bans, the ban went elsewhere and the six needs an answer to it. A Mauga is answered by the supports swapping to Ana or Zenyatta; a hero left unbanned while the team bans her counter dominates the lobby. Measured as the count of revealed red picks answered by at least one of ours, while red's highest ban rate is 30 percent or more.
