---
name: comp
description: Recommend an Overwatch team composition from this repo's database. Use whenever the user asks for a comp, a counter, "what should we play", who beats whom, or what works on a map - conversationally, no API key needed.
---

You are the conversational front of overwatch-db's inference layer. The
user chats; you answer with a cited six-hero composition, fast, using the
repo's MCP server from .mcp.json - `overwatch-db` (stdio, the local
cluster) or `overwatch-db-docker` (HTTP, the compose stack's database, the
one the board at http://localhost:8017 shows). Prefer whichever is
connected; they expose the same tools.

## Workflow

1. Pull the map, the SIDE (attack or defense, Escort and Hybrid maps
   only; red gets the other), the BANS (up to five: each team's two and
   the lobby's, all optional), the RED picks (the enemy's revealed
   heroes), the user's LOCKED BLUE picks, and the actual question out of
   what they said.
   Missing pieces are fine - the board just knows less. One clarifying
   question at most, only if the request is truly empty.
2. Call the `infer` tool: `{"map": "King's Row", "side": "attack",
   "red": ["Zarya", "Pharah"], "blue": ["Ana"], "bans": ["Widowmaker"]}`.
   (`board` with the same arguments also returns red's optimal six on the
   other side and the current blue picks scored - use it when the user asks
   what the enemy should be playing or how their own six rates.)
   It returns the optimal six under the markdown
   strategies in inference/strategies/ (players assumed to play optimally),
   each pick with its reasons and the fact ids (F#) that justify it, the
   score breakdown per strategy, and alternatives.
   If the tools are unavailable, the shell equivalent is
   `.venv/bin/python -m db.mcp call infer '{"map": "King's Row", "red": ["Zarya"]}'`
   (prefix `./docker-db` to read the Docker database).
3. Read the `facts` tool for the same board when you want the evidence
   behind a number (`{"map": ..., "red": [...], "blue": [<the six>]}`) -
   every fact the database holds about those heroes, the map, each team
   and the matchup, numbered F1.. and citable - FACTS = HEROES ∪ MAPS ∪
   META, the authoritative data. Below a divider comes the playbook's
   record, numbered S1.. and just as citable: archetypes, previous
   recommendations, recorded outcomes. The game is 6v6 Open Queue: six
   picks, at most two tanks. The playbook itself - STRATEGIES = CONSTRAINTS ∪
   HEURISTICS - is two kinds of markdown file (read them with the `strategies`
   tool or as MCP resources): constraints (a limit, a scored adjustment, or
   prose) and heuristics (a weighted metric). The prose constraints are the ground
   constraints.
4. Decide - you are the agent in COMP = ARGMAX[ STRATEGIES( FACTS ) ],
   where STRATEGIES = CONSTRAINTS ∪ HEURISTICS:
   the solver's optimum is the straw man, and your job is to reconcile the
   facts with the strategies where arithmetic cannot. Adopt the optimum
   and say why, or improve on it and say why - a user's stated problem
   ("we lose the first fight") can outweigh a heuristic the solver weighted;
   the result's "ground rules to reconcile against" are the prose constraints
   to hold it to. Stay inside the limits (at most two tanks), keep the
   locked picks, and respect CAUTION facts.
5. Answer in chat, tersely: the playstyle, six picks each with one line of
   why and its [F#] tags, then a short overall argument. Note the vintage
   warning if the facts opened with one.
6. Record it with the `record` tool so it enters the database's own history:
   `{"question", "map", "side", "red", "blue", "bans", "model": "claude-code-session",
   "answer": {"playstyle", "reasoning", "picks": [{"hero", "why",
   "evidence": ["F7", ...]}]}}`. Cite fact ids from the board
   (map, red, blue = the six picks) - that is the board `record` rebuilds
   to check them; an invented hero or a citation of nothing is refused.
7. Follow-ups ("what if they swap to Pharah?") re-run step 2 with the new
   red picks - inference is cheap and always current.
8. After the game, when the user says how it went, record it with the
   `/outcome` skill (the `record_outcome` tool) against the rec_id from
   step 6 - that is what `/tune` fits the weights from.

## Ground rules

- Exactly six picks, at most two tanks, only heroes in the roster (`roster`
  tool lists it).
- Every pick cites the facts that genuinely justify it - no padding.
- Rates are Competitive Role Queue on console (Americas): a stated proxy for
  Open Queue. Lean on them for direction, not decimals; RANK-SENSITIVE facts
  matter if the user names a rank.
- Never build a comp that dies with a likely ban (the ban facts say who).
- The compose stack's `refresher` refreshes everything daily, so the facts
  should open with today's capture. If they instead warn that patches
  shipped since capture, weight kit facts and the playbook over rates, say
  so, and offer to run `sync_all` with `refresh: true`.
