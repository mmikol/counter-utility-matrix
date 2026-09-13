---
name: up
description: Bring the whole overwatch-db stack up and current - database, data layer (MCP), inference engine, board, refresher - and report the URLs and the data's vintage. Use when the user says to start, run, launch or check the app, or wants everything "good to go" before a game.
---

Bring everything up and prove it is ready. Run, from the repo root:

    python orchestrator.py up          # or `python orchestrator.py` to also run the agents

It builds the one image, starts one container per layer (`db`, `data`,
`inference`, `ui`, `refresher`), waits for each layer's health, and prints
a verdict. A first build scrapes the sources once (minutes); later starts
take seconds. Then:

1. Read the verdict. `READY` means: the data layer answers with no pending
   migrations and a populated database, the inference engine sees the
   strategies, the board serves the roster. Report the URLs it prints
   (board http://localhost:8017, inference :8019, MCP over HTTP :8020/mcp)
   and the line "rates captured YYYY-MM-DD".
2. `NOT READY` names the problem. The usual fixes, in order: a stale bind
   mount after moving directories -> `docker compose up -d --force-recreate`
   (the script already tries this once); a schema behind the migrations ->
   the `data` container rebuilds on its own, wait and run
   `python orchestrator.py status` again; the database never became reachable ->
   `docker compose logs db`.
3. If the rates capture date is not today and the user is about to play,
   offer `python orchestrator.py refresh` (or the `sync_all` tool with
   `refresh: true` on the `overwatch-db-docker` MCP server). The refresher
   container refreshes daily on its own and on start when the caches are a
   day old, so this is rarely needed.
4. Never run `docker compose down -v`: that deletes the database volume
   (recorded comps and outcomes come back from the db/raw mirror, but
   the rebuild costs a scrape).

`python orchestrator.py status` answers "is it up?" without touching anything;
`python orchestrator.py test` runs the suite inside the image.
