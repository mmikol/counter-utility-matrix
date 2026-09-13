---
name: Punish a one-note enemy comp
kind: constraint
category: matchup
when: matchup.style_lean_red == 'dive'
bonus: min(team.cc_count, 2) * 0.5 + min(team.barrier_count, 1) * 0.5
---
# Punish a one-note enemy comp

When a strict majority of the revealed enemies carry the dive tag, the
answer is peel and a wall to dive into: crowd control and a barrier.
The `peel-against-dive` constraint reads engage tools; this one reads the
judged style, so both fire against a real dive comp and only one
against a coincidence.
