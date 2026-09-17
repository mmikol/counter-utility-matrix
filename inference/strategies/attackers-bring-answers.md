---
name: Attackers bring the answers
kind: heuristic
category: side
metric: team.coverage
direction: maximize
weight: 1
when: map.side == 'attack'
---
# Attackers bring the answers

On attack the six that answers more of red's picks wins the one fight it needs, because attackers can re-pick between fights while a defense that has set up cannot. The community calls rock-paper-scissors matchups horrible for defenders precisely because little prevents the attackers from blowing ults and swapping to the counter comp each time the defense gets set up. Measured as the count of revealed red picks answered by at least one of ours, on the attacking side of a sided map.
