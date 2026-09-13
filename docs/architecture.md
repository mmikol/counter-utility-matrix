# How it all fits together

Three layers over one database, and the door between them.

## The three layers

```mermaid
flowchart LR
    subgraph SOURCES["sources (free, no data APIs)"]
        BLZ["Blizzard<br/>roster, portraits, rates"]
        WIKI["Overwatch wiki<br/>kits, numbers, keywords,<br/>maps, patches, styles"]
        CPK["counterpick.gg<br/>counters, best maps"]
        CSV["authored files<br/>synergies, archetypes,<br/>map styles, seasons, notes"]
    end

    subgraph DATA["DATA LAYER - data/mcp/ (an MCP server)"]
        PULL["pull_* tools<br/>fetch (cached) -> clean -> store"]
        PLAY["load_playbook<br/>the authored inputs +<br/>the heuristics mirror"]
        DBT["db_* · query · export_csv"]
    end

    subgraph PG["PostgreSQL - 40 tables"]
        HEROES["HEROES<br/>roster, kits, stats,<br/>keywords, portraits"]
        MAPS["MAPS"]
        META["META<br/>dated snapshots"]
        PLAYBOOK["PLAYBOOK<br/>counters, synergies,<br/>styles, heuristics mirror"]
        INF["INFERENCE<br/>recorded comps"]
    end

    subgraph USER["USER LAYER - user/facts/ + user/board.py"]
        WORLD["World<br/>the database in memory,<br/>per request"]
        FACTS["FactSet F1..<br/>hero · map · team ·<br/>matchup · playbook"]
        BOARD["the board<br/>map + red/blue rosters"]
    end

    subgraph INFER["INFERENCE LAYER - inference/"]
        HEUR["heuristics/*.md<br/>constraint · goal · strategy"]
        SOLVER["solver<br/>enumerate · prune ·<br/>normalise · refine"]
        REC["record<br/>gates + transcript"]
    end

    BLZ & WIKI & CPK --> PULL
    CSV --> PLAY
    HEUR --> PLAY
    PULL & PLAY --> PG
    PG --> WORLD --> FACTS --> BOARD
    WORLD --> SOLVER
    HEUR --> SOLVER
    SOLVER --> BOARD
    SOLVER --> REC --> INF
    CHAT["Claude Code session<br/>/comp skill"] <-->|"MCP tools:<br/>pull_*, facts, infer, record"| DATA
```

The data layer owns the writes to Postgres. The user layer only reads,
turns every table into facts, and computes every metric in one place
(`user/facts/compute.py`) so the number on the board and the number the
solver scores are the same function. The inference layer reads the facts,
never the tables.

The equation the whole repo serves:

```
FACTS = HEROES ∪ MAPS ∪ META ∪ PLAYBOOK ∪ HISTORY     the whole database, for one board
COMP  = ARGMAX[ STRATEGIES( FACTS ) ]                  constraints prune, goals weigh,
                                                       strategies adjust; the agent argues
```

`STRATEGIES( FACTS )` is the score the solver maximises; the inference
agent (a Claude Code session on the `/comp` skill) reads the same facts and
the same strategies and reconciles them where arithmetic cannot - a stated
problem, a lobby's habits, a patch the rates predate.

## One click on the board

```mermaid
sequenceDiagram
    actor You
    participant Board as user/board.py
    participant Facts as user/facts/ (World + FactSet)
    participant Solver as inference/ (solver)
    participant DB as PostgreSQL

    You->>Board: pick the map, set the bans, click red picks<br/>as they reveal, lock your blue picks
    Board->>Facts: /api/facts (map, red, blue, bans)
    Facts->>DB: load the World (a dozen queries)
    Facts-->>Board: F1..Fn - every fact about those heroes,<br/>the map, each team, the matchup
    Board->>Solver: /api/infer (map, red, blue, bans)
    Solver->>Solver: shapes the constraints allow · per-role pools ·<br/>every candidate scored · local search
    Solver->>Facts: the FactSet for (map, red, the optimal six)
    Solver-->>Board: the six with reasons and [F#] citations,<br/>score per heuristic, alternatives
    You->>Board: "record this comp"
    Board->>Solver: record: gates (six real heroes,<br/>citations the board showed), tables, transcript
```

With six blue picks locked the same endpoint evaluates your six against
the field the solver would have searched, and says where it ranks.

## The life of the database

```mermaid
stateDiagram-v2
    [*] --> Empty: docker compose up<br/>(or pgserver first touch)
    Empty --> Schema: db_init<br/>8 migrations, 40 tables
    Schema --> Populated: sync_all<br/>7 pull tools + load_playbook
    Empty --> Populated: db_rebuild<br/>(the entrypoint's move<br/>on an empty database)
    Populated --> Populated: sync_all / any pull_*<br/>(the refresher, daily)<br/>entities upsert in place,<br/>rates APPEND a dated snapshot
    Populated --> Empty: db_rebuild<br/>drop everything...
    note right of Populated
        ...but recorded recommendations
        are restored from the data/raw
        mirror after every rebuild -
        the one thing no tool can
        re-fetch is never discarded.
    end note
```

`python -m data.orchestrator <verb>` drives the same tools without a session;
Docker's `data` container runs `rebuild` on an empty or stale database and
the `refresher` container runs `sync_all` with refresh on once a day (and
on start when the cached pages are older than a day). A page that fails
to refetch keeps its cached copy, so a bad day at a source degrades to
yesterday's numbers rather than an empty table.

## Where every kind of data lives

Any data in the database is just data: every row carries its `source_id`,
and that is the only distinction the schema draws. What differs is how a
row gets there - and therefore what a rebuild can and cannot recover.

```mermaid
flowchart TD
    Q{"Can a pull tool<br/>re-fetch it?"}
    Q -->|"yes"| F["pulled<br/>blizzard · wiki · counterpick<br/>data/extract -> transform -> load"]
    Q -->|"no - we wrote it"| A["authored<br/>data/authored/: synergies, archetypes,<br/>map playstyles, seasons, notes<br/>+ inference/heuristics/*.md (the brain)"]
    Q -->|"no - the inference<br/>layer decided it"| R["recorded<br/>recommendations + transcripts,<br/>mirrored to data/raw, restored<br/>after every rebuild"]
```

## Deployment: one container per layer

```mermaid
flowchart LR
    subgraph HOST["your machine"]
        SESSION["Claude Code session<br/>/comp skill"]
        BROWSER["browser"]
        SHELL["./docker-db<br/>DATABASE_URL -> :5433"]
    end
    subgraph DOCKER["docker compose (one image, four containers)"]
        DATA["data - DATA LAYER<br/>builds when empty or stale,<br/>then MCP over HTTP :8020/mcp"]
        INF["inference - INFERENCE ENGINE<br/>:8019 infer · evaluate ·<br/>heuristics · record"]
        UI["ui - USER LAYER<br/>:8017 the board<br/>facts in-process,<br/>comps via INFERENCE_URL"]
        DBC["db - postgres:16<br/>volume pgdata"]
        REF["refresher - the clock<br/>sync_all(refresh) daily,<br/>and on start when stale"]
    end
    SESSION -->|".mcp.json: overwatch-db-docker"| DATA
    BROWSER --> UI
    UI -->|"HTTP"| INF
    UI --> DBC
    INF --> DBC
    DATA --> DBC
    SHELL --> DBC
    REF --> DBC
```

`docker-entrypoint.sh` takes the role as its argument (`data`,
`inference`, `ui`); `inference` and `ui` wait until the data layer reports
the database current, and compose's healthchecks order the start the same
way. Bind mounts keep the page caches, `data/raw`, `data/authored` and
`inference/heuristics/` on the host, so tuning a heuristic or authoring a
synergy needs no image rebuild.

Local-only works identically: without `DATABASE_URL`, everything runs in
one process against the embedded pgserver cluster at `data/db/cluster` - the
MCP server over stdio, the board with the engine in-process - same tools,
same facts, same heuristics.
