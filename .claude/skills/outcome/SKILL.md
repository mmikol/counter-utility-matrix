---
name: outcome
description: Record how a match went so overwatch-db can learn from it - the result, the map and side, both teams' six, the bans, and which recommendation was played. Use when the user reports a win, loss or draw, says "we won/lost with ...", or asks to log a game.
---

Record the match through the `record_outcome` tool on the `overwatch-db`
(or `overwatch-db-docker`) MCP server.

1. Pull out of what the user said: the RESULT (win, loss, draw), the MAP,
   blue's SIDE on Escort/Hybrid maps, BLUE's six (required - it is what
   the fit scores), RED's picks (as many as they saw), the BANS, and the
   recommendation they played if any (`rec_id` - the number the `/comp`
   skill or the board's "record this comp" reported; `recs` on the board
   lists them). One line of NOTE if they said what decided it.
2. Call `record_outcome`: `{"result": "win", "map": "King's Row",
   "side": "attack", "blue": [...six...], "red": [...], "bans": [...],
   "rec_id": 22, "note": "held the first fight every round"}`. The gates
   refuse unknown heroes, a banned pick, or fewer than six blue picks -
   ask for the missing pick rather than guess.
3. Report the running tally the tool returns (wins-losses-draws), and
   once it reaches ten decided matches, offer `/tune` to fit the weights.

Outcomes are mirrored to data/raw with the recorded comps and restored
after every rebuild; they show up as facts on the board (per hero and per
map) and in the `facts` tool.
