# How it all fits together

Four pictures: the whole machine, one game played with it, the life of the
database, and where every kind of data lives. All diagrams render on GitHub.

## The whole machine

Scrapers fill Postgres; the dossier turns Postgres into numbered evidence;
a Claude Code session (the `/comp` skill) reads that evidence and decides;
the decision is gated, recorded, and becomes evidence for next time. The
UI is a window onto the same pipeline — it computes nothing of its own.

```mermaid
flowchart LR
    subgraph SOURCES["sources (free, no data APIs)"]
        BLZ["Blizzard rates page<br/>win / pick / ban"]
        WIKI["Overwatch wiki<br/>heroes, kits, maps, patches"]
        CPK["counterpick.gg<br/>counters, map picks"]
        CSV["authored CSVs<br/>synergies, archetypes, seasons,<br/>map playstyles, heuristics + dials"]
    end

    subgraph PIPE["orchestrator.py - 13 pipelines"]
        AUTH["authoritative<br/>(measured)"]
        HEUR["heuristic<br/>(judged, scraped)"]
        PROP["proprietary<br/>(ours, authored)"]
    end

    subgraph PG["PostgreSQL - 40 tables"]
        HEROES["HEROES<br/>roster, abilities, stats"]
        MAPS["MAPS<br/>maps, modes, stages"]
        META["META<br/>snapshots, rates,<br/>patches, seasons"]
        PLAY["PLAYBOOK<br/>counters, synergies, styles,<br/>heuristics + heuristic_params"]
        INF["INFERENCE<br/>recommendations,<br/>picks, evidence"]
    end

    DOS["dossier.py<br/>~150 numbered [E#] lines:<br/>facts, intersections,<br/>37 live derived: formulas"]

    subgraph CHAT["Claude Code session (your subscription, $0 API)"]
        SKILL["/comp skill<br/>reads every line, argues,<br/>picks five heroes"]
        REC["record.py -> store.py gates:<br/>5 real heroes, real citations,<br/>or refused"]
    end

    subgraph UIBOX["ui.py :8017"]
        BOARD["live evidence board<br/>click their picks + yours,<br/>select map, evidence follows"]
        DASH["dashboard + /rec/id viewer"]
    end

    BLZ --> AUTH
    WIKI --> AUTH
    WIKI --> HEUR
    CPK --> HEUR
    CSV --> PROP
    AUTH --> PG
    HEUR --> PG
    PROP --> PG
    HEROES & MAPS & META & PLAY & INF --> DOS
    DOS -->|"the same lines"| SKILL
    DOS -->|"/api/dossier"| BOARD
    SKILL --> REC
    REC -->|"persist + transcript"| INF
    INF -->|"/api/recs poll"| BOARD
    PG --> DASH
```

The equation the whole repo serves:

```
COUNTER = MAX[ HEROES ∩ MAPS ∩ META ]
```

The database supplies the three sets, the playbook supplies the judgement,
the heuristics catalog supplies the arithmetic, and the session supplies
the argument. Claude never generates evidence — it only cites what the
deterministic SQL produced.

## One game, played with it

```mermaid
sequenceDiagram
    actor You
    participant Board as ui.py board<br/>(:8017/recommend)
    participant Claude as Claude Code session<br/>(/comp skill)
    participant Dossier as dossier.py
    participant DB as PostgreSQL

    You->>Board: select map, click enemy picks as they reveal
    Board->>Dossier: GET /api/dossier (map, enemies, allies)
    Dossier->>DB: deterministic SQL + 37 live heuristics
    DB-->>Board: ~150 [E#] evidence lines, live on every click

    You->>Claude: "/comp - King's Row, they have Zarya + Pharah,<br/>I'm locked on Ana. What do we play?"
    Claude->>Dossier: python -m data.proprietary.dossier<br/>--map ... --enemy ... --ally ...
    Dossier->>DB: the same SQL, the same lines
    DB-->>Claude: the same ~150 [E#] lines
    Claude->>Claude: reads every line, argues against<br/>the skeleton, decides five heroes
    Claude->>DB: record.py - store gates refuse invented<br/>heroes or citations-of-nothing
    DB-->>Board: /api/recs poll: "the session just<br/>recorded recommendation #22"
    You->>Board: click through to /rec/22 -<br/>every pick with its cited evidence
```

The board and the skill are two windows onto one dossier: what you see on
`/recommend` is exactly what the model reads — nothing more, nothing less.

## The life of the database

```mermaid
stateDiagram-v2
    [*] --> Empty: docker compose up<br/>(or pgserver first touch)
    Empty --> Schema: init<br/>7 migrations, 40 tables
    Schema --> Populated: inflate<br/>all 13 pipelines
    Empty --> Populated: rebuild<br/>(the entrypoint's move<br/>on an empty database)
    Populated --> Populated: update<br/>entities upsert in place,<br/>meta APPENDS a dated snapshot
    Populated --> Empty: rebuild<br/>drop everything...
    note right of Populated
        ...but recorded recommendations
        are restored from the data/raw
        mirror after every rebuild -
        proprietary output is the one
        thing no pipeline can re-fetch,
        so no rebuild may discard it.
    end note
```

Each verb refuses the state it is not for and names the verb you wanted.
`update` is the default and the cron updater's verb (coded, disabled
behind the compose profile `cron`). Every meta update appends a snapshot
delineated by **patch and season**, so the series accumulates and
`derived:trend` has something to difference.

## Where every kind of data lives

```mermaid
flowchart TD
    Q{"Can a rebuild<br/>re-fetch it?"}
    Q -->|"yes, it was measured"| A["authoritative<br/>hero stats, rates, patches<br/><i>source: Blizzard, wiki</i>"]
    Q -->|"yes, it was judged<br/>by someone else"| H["heuristic<br/>counters, playstyles<br/><i>source: counterpick.gg, wiki</i>"]
    Q -->|"no - it is ours"| P["proprietary<br/><i>committed CSVs + recorded output</i>"]
    P --> P1["authored judgement:<br/>synergies, archetypes,<br/>map playstyles, seasons"]
    P --> P2["the tunable brain:<br/>heuristics (100 formulas),<br/>heuristic_params (the dials)"]
    P --> P3["recorded output:<br/>recommendations + transcripts,<br/>mirrored to data/raw, restored<br/>after every rebuild"]
```

The dials in `heuristic_params` are why the playbook is a *brain* and not
a config file: edit a threshold in the CSV, re-run the loader, and the
next dossier — board or skill, host or Docker — computes with it. No code
change, no redeploy. The full catalog with every formula is
[heuristics.md](heuristics.md).

## Deployment shapes

```mermaid
flowchart LR
    subgraph HOST["your machine"]
        SESSION["Claude Code session<br/>/comp skill"]
        BRIDGE["./docker-db<br/>DATABASE_URL -> :5433"]
        BROWSER["browser -> :8017"]
    end
    subgraph DOCKER["docker compose"]
        APP["app: ui.py<br/>entrypoint: rebuild if empty,<br/>then serve"]
        DBC["db: postgres:16<br/>volume pgdata"]
        CRON["updater (profile: cron)<br/>coded, disabled"]
    end
    SESSION --> BRIDGE --> DBC
    BROWSER --> APP --> DBC
    CRON -.->|"when enabled:<br/>update every 24h"| DBC
```

Local-only works identically: without `DATABASE_URL`, everything falls
back to the embedded pgserver cluster at `db/cluster` — same code, same
verbs, same evidence.
