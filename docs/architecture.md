# How it fits together

Three layers over one database, each a folder at the root, each with its
own document in `docs/`.

```
DATA           = HEROES ∪ MAPS ∪ META              the tables, as pulled and set
for each domain D in { HEROES, MAPS, META }:
  INDEPENDENT(D) = ⋃ facts(s)      over each selection s in D    s alone: its own row
  DEPENDENT(D)   = ⋃ facts(s ⋈ t)  over the other selections t   s joined with t, in D or beyond
  FACTS(D)       = INDEPENDENT(D) ∪ DEPENDENT(D)
FACTS          = FACTS(HEROES) ∪ FACTS(MAPS) ∪ FACTS(META)
FACTS(D) ∩ FACTS(E) = the joins of D with E: what only their intersection can say
STRATEGIES     = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS   the playbook: markdown files
COMP           = ARGMAX[ STRATEGIES( FACTS ) ]            the solver searches, the agent argues
```

No accounts, no keys, no API billing. The board is a local page and the
solver is deterministic; the model work (comps in chat, strategies
inferred from prose, the refresh that tunes with a reason) runs in Claude
Code on your subscription, before a game, never during one.

## The folders

| folder | what it is | read |
| --- | --- | --- |
| `db/` | **DATA LAYER** - `data/` and `psql/` pull every source, clean it and store it, with the schema, its migrations and the embedded cluster. A wiki stat is stored as measurements beside its original text (`data/wiki/measurements.py`); the UI layer's `ui/facts/kit.py` reads a kit's combat numbers off both at read time, so a misread wording is fixed there and needs no re-pull. `mcp/` and `sentry` stand over all three layers rather than inside this one: the door serves the UI layer's facts and the inference layer's solver through the same tools, and the guard watches the playbook beside the database. The door gates every write; the other two layers read Postgres directly, over `db.psql.default_dsn()` | [db.md](db.md) |
| `ui/` | **UI LAYER** - the board (map, sides, bans, red and blue rosters) and the facts behind it: the World, the metrics registry, the FactSet | [ui.md](ui.md) |
| `inference/` | **INFERENCE LAYER** - the playbook of constraints, heuristics and assumptions in markdown, the solver, the tuning loop, the deriver | [inference.md](inference.md) |
| `tests/` | one folder per layer (`tests/db`, `tests/ui`, `tests/inference`), the root files' tests beside them (`test_docs.py`, `test_orchestrator.py`), `synthetic.py`, a World of twelve invented heroes and three maps built by hand, which the metric, derivation and board-facts tests work their expected values from with no database, and `tests/fixtures/playbook/`, the reference playbook every kind and form of strategy is proven against while `inference/strategies/` holds the user's assumptions (its rules were emptied on purpose and are being rebuilt by hand; `inference/README.md` is the record). `pytest -q` runs them, skipping what needs a built database when there is none | |
| `.claude/skills/` | what a Claude Code session can do here: `/up`, `/comp`, `/tune`, `/strategy`, `/patches`, `/heroes`, `/maps`, `/refresh`, `/maintain` | [skills.md](skills.md) |
| `pm/` | `backlog.md`: what is worth doing next, why and at what cost, in payoff order; the maintainer skill keeps it current | |
| `scripts/` | the recorders of the proven fixtures, run from the repo root as modules. `optimal` (`python -m scripts.optimal`) records the true maximum of proven boards into `tests/fixtures/optimal.json`, which `tests/inference/test_optimal.py` re-solves on every run - the regression gate on the search. It reads the brute force's `.jsonl` output from the paths in `OPTIMAL_SOURCES`, which live outside the repo. `reach` (`python -m scripts.reach`) records a board per released hero into `tests/fixtures/reach.json`. Each fixture records the digest of the playbook it was proved under. The gate skips while the shipped playbook scores nothing, fails with "recorded under a different playbook" under any other playbook that scores, and holds out banned boards (`OPTIMAL_STALE_BANNED`) until the backlog's re-prove lands. Run after a deliberate change to the objective, and say in the commit why every number moved | |
| `.github/workflows/` | `ci.yml`: lint and the tests that need no built database, held to 78% coverage, on pushes to `main` and on pull requests | |
| `.cache-blizzard/` `.cache-wiki/` | the page caches (gitignored): every build after the first costs almost no requests | |

How they fit:

```mermaid
flowchart LR
    subgraph SOURCES["sources (free, no data APIs)"]
        BLZ["Blizzard<br/>roster, portraits, rates"]
        WIKI["Overwatch wiki<br/>kits, numbers, keywords,<br/>maps, patches, seasons,<br/>styles, synergies, counters"]
    end

    subgraph DATA["DATA LAYER - db/mcp/ (an MCP server)"]
        PULL["pull_* tools<br/>fetch (cached) -> clean -> store"]
        PLAY["load_authored<br/>the strategies mirror"]
        DBT["db_* · query · export_csv"]
    end

    subgraph PG["PostgreSQL"]
        HEROES["HEROES<br/>roster, kits, stats,<br/>keywords, portraits"]
        MAPS["MAPS"]
        META["META<br/>dated snapshots"]
        PLAYBOOK["PLAYBOOK<br/>counters, synergies,<br/>styles"]
        INF["INFERENCE<br/>the strategies mirror"]
    end

    subgraph USER["UI LAYER - ui/facts/ + ui/board.py"]
        WORLD["World<br/>the database in memory,<br/>per request"]
        FACTS["FactSet<br/>F1.. hero · map · meta ·<br/>team · matchup<br/>S1.. the playbook's record"]
        BOARD["the board<br/>map + red/blue rosters"]
    end

    subgraph INFER["INFERENCE LAYER - inference/"]
        HEUR["strategies/*.md<br/>STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS<br/>constraint: limit · scored"]
        SOLVER["solver<br/>enumerate · prune ·<br/>normalise · refine"]
    end

    BLZ & WIKI --> PULL
    HEUR --> PLAY
    PLAY --> INF
    PULL & PLAY --> PG
    PG --> WORLD --> FACTS --> BOARD
    WORLD --> SOLVER
    HEUR --> SOLVER
    SOLVER --> BOARD
    CHAT["Claude Code session<br/>/comp skill"] <-->|"MCP tools:<br/>pull_*, facts, infer, board"| DATA
```

The data layer owns every write to Postgres and the playbook. The UI
layer reads, turns every table into facts, and defines every metric once
(`ui/facts/team.py` the team's, `ui/facts/compute.py` the rest, and
`compute.registry()` gathers them), so the number on the board and the
number the solver scores are the same function; its one write, a heuristic's weight
stored from the board, is off by default (`COUNTRIX_READ_ONLY`)
and, when turned on, is handed to the data layer's `tune` tool. The
inference layer reads the facts, never the tables.

The equation divides the layers. The data layer owns DATA. The UI layer's
fact engine owns FACTS: per domain, the independent facts (a selection's
own row - a hero's kit, rates and style; the map's mode and styles; the
meta's vintage) and the dependent ones (that selection joined with
others: the hero on this map, against each enemy, beside each ally, the
six aggregated, the twelve compared, a banned hero against both teams'
counters). The inference layer owns STRATEGIES - three kinds of file: a
*constraint* (a limit, hard unless soft, or a scored adjustment while a
condition holds), a *heuristic* (a metric weighed, maximised or
minimised), an *assumption* (prose taken as given, never scored) - and
the argmax. The solver maximises `STRATEGIES( FACTS )`; the agent (a
Claude Code session on `/comp`) reads the same facts and strategies and
reconciles them where arithmetic cannot. Facts are numbered F1.., the
playbook's record below them S1.., so both are citable and neither is
mistaken for the other.

## The files

| file | purpose |
| --- | --- |
| `orchestrator.py` | the end-to-end run. `.venv/bin/python orchestrator.py` brings the stack up (the data container pulls and ingests when the database is empty or stale), runs the agents headless on the `/refresh` skill, and leaves the app running. Verbs: `run` (default) · `up` · `agents` · `status` · `refresh` · `test` · `down` |
| `compose.yaml` | one container per layer from one image: `db` (PostgreSQL 16), `data` (builds the database, then the MCP server over HTTP), `inference` (the engine as a service), `ui` (the board), `refresher` (the daily clock), `sentry` (the guard). Every container is unprivileged on a read-only root with no capabilities; every published port binds to 127.0.0.1 and nothing is published ([deploy.md](deploy.md)). Bind mounts keep the caches, `db/raw`, `inference/strategies` and `docs` on the host, so tuning, authoring and regenerating need no rebuild |
| `Dockerfile` | the one image, run as an unprivileged user (uid 1000, or `COUNTRIX_UID`/`GID` from `.env` on a Linux host whose checkout is owned by someone else); `docker-entrypoint.sh` takes the role as its argument and, for `data`, builds the database when it is empty, unfilled or behind the migrations |
| `docker-db` | run any host command against the compose database: `./docker-db .venv/bin/python -m db.mcp call infer '{"map": "Ilios"}'` |
| `.mcp.json` | registers the two MCP servers a Claude Code session sees: `countrix` (stdio, the local cluster) and `countrix-docker` (HTTP, the stack's database) - [mcp.md](mcp.md) |
| `requirements.txt` | psycopg, requests, beautifulsoup4 and pgserver pinned (pgserver is the embedded PostgreSQL a host build uses; the image and CI filter it out, since neither starts a cluster), then pytest, pytest-cov and ruff |
| `pyproject.toml` | ruff's rules (line length 100); the coverage bar, 75% where a database exists |
| `pytest.ini` | the `invariant` marker for tests that need a built database |
| `CLAUDE.md` | what a Claude Code session reads before it changes code: the commands, the layers in brief, what the tests hold a change to, the house rules and style |
| `SECURITY.md` | the terms - you run it at your own risk, no security commitment from the author - and how to report a vulnerability privately; the measures themselves are in [security.md](security.md) |
| `LICENSE` | PolyForm Strict 1.0.0: noncommercial use only, no redistribution, no changes or new works; anything else needs a separate license from the author |
| `.gitignore` `.dockerignore` | the caches, the cluster, the mirror, the venv, `.env` |

## Deployment

```mermaid
flowchart LR
    subgraph HOST["your machine"]
        SESSION["Claude Code session<br/>/comp skill"]
        BROWSER["browser"]
        SHELL["./docker-db<br/>DATABASE_URL -> :5433"]
    end
    subgraph DOCKER["docker compose (one image, five containers, plus postgres)"]
        DATA["data - DATA LAYER<br/>builds when empty or stale,<br/>then MCP over HTTP :8020/mcp"]
        INF["inference - INFERENCE ENGINE<br/>:8019 infer · evaluate ·<br/>board · strategies"]
        UI["ui - UI LAYER<br/>:8017 the board<br/>facts in-process,<br/>comps via COUNTRIX_INFERENCE_URL"]
        DBC["db - postgres:16<br/>volume pgdata"]
        REF["refresher - the clock<br/>seasons + rates daily,<br/>every source weekly,<br/>and on start when stale"]
        SEN["sentry - the guard<br/>the playbook, the database's text,<br/>the door's audit log"]
    end
    SESSION -->|".mcp.json: countrix-docker"| DATA
    BROWSER --> UI
    UI -->|"HTTP"| INF
    UI --> DBC
    INF --> DBC
    DATA --> DBC
    SHELL --> DBC
    REF --> DBC
    SEN --> DBC
```

The containers share one network; only `data` and `refresher` ever open a
connection out. `docker-entrypoint.sh` takes the role as its argument
(`data`, `inference`, `ui`, `refresh`, `sentry`). Readiness has one
definition, `db.psql.schema.state`: empty, stale (a migration the ledger
lacks), unfilled (no heroes) or current. The entrypoint asks it through
`python -m db.psql.schema`; `inference`, `ui` and `refresh` wait for
current, up to the data healthcheck's 900 s, then exit. The data
container's `/health` carries the state, and compose's healthcheck and
`orchestrator.py` wait on it. [security.md](security.md) has the rest of
the measures.

Settings, from the environment or `.env` (the refresh times are in [db.md](db.md)).
Each is read where it is used, so a change takes effect on the next call -
except where a server listens (the UI and inference host and port), the MCP
server's token, `COUNTRIX_WORKERS` (read when the pool starts), the refresh
clock and the sentry interval, which are read once at start:

| setting | default | meaning |
| --- | --- | --- |
| `COUNTRIX_STRATEGIES` | empty | a playbook folder other than `inference/strategies/`, relative to the repo root or absolute |
| `COUNTRIX_WORKERS` | `max(6, min(cores, 12))` | the solver's worker processes |
| `COUNTRIX_PARALLEL` | `1` | `0`: every board in one process |
| `COUNTRIX_UI_HOST`, `COUNTRIX_UI_PORT` | `127.0.0.1`, `8017` | where the board listens |
| `COUNTRIX_READ_ONLY` | `1` | the board writes nothing: a slider's weight is the session's own; `0` brings back *store* |
| `COUNTRIX_INFERENCE_HOST`, `COUNTRIX_INFERENCE_PORT` | `127.0.0.1`, `8019` | where the inference service listens |
| `COUNTRIX_INFERENCE_URL` | unset | the inference service the board delegates to; the engine runs in-process when unset. http or https: any other scheme stops the board at launch |
| `COUNTRIX_MCP_TOKEN` | unset | bearer token the MCP server requires over HTTP |
| `COUNTRIX_AUDIT` | `db/raw/audit.jsonl` | the MCP server's audit log |
| `COUNTRIX_SENTRY_EVERY` | `30` | seconds between sentry sweeps |
| `COUNTRIX_CLAUDE` | the `claude` on `PATH` | the CLI the agents and `derive` run |
| `COUNTRIX_MCP_URL` | unset | the MCP server the board's one write goes to; in-process through the same registry when unset. http or https, like the inference URL |
| `COUNTRIX_REPO_URL` | `https://github.com/mmikol/countrix` | the repository the board's header links to |
| `DATABASE_URL` | unset | the PostgreSQL to use; the embedded cluster at `db/psql/cluster` when unset |

Local-only works identically: without `DATABASE_URL`, everything runs in
one process against the embedded pgserver cluster at `db/psql/cluster` -
the MCP server over stdio, the board with the engine in-process - same
tools, same facts, same strategies.

## The skills

Open the repo in a [Claude Code](https://claude.com/claude-code) session
and the `.claude/skills/` are yours; each is a playbook over the MCP
tools. [skills.md](skills.md) documents them, [mcp.md](mcp.md) the
servers and every tool.

| skill | does |
| --- | --- |
| `/up` | brings the stack up and current, and proves it: URLs, health, the rates' capture date |
| `/comp` | "comp for King's Row, they have Zarya and Pharah, I'm on Ana": calls `infer` and `facts`, argues against the solver's optimum under the assumptions, answers with `[F#]` citations |
| `/tune` | changes a weight, a dial or an expression through `tune` |
| `/strategy` | asks for a name, a kind and prose, infers the frontmatter and stores the strategy through `add_strategy` |
| `/patches` | pulls the patch list and, when a patch shipped since the capture, refetches what it changes: rates, kits, Blizzard's text |
| `/heroes` | adds or refreshes heroes: Blizzard's roster, the wiki's kits, styles and synergies, the announced heroes ahead of release, counters |
| `/maps` | adds or refreshes maps: the pool, modes and stages, the per-map rates, the style each map's rates reward |
| `/refresh` | the agents' run, the one `orchestrator.py agents` executes headless: refresh, complete drafts, re-infer with restraint, regenerate, report |
| `/maintain` | the repo's maintainer: lint and tests three ways, docs current, stale names, dead code, layout, security posture, a report |

The skills run on your subscription; no API key, no per-token bill.

## Scope, honestly

6v6 Open Queue Competitive is the target: six picks a side in any mix of
roles, at most two tanks. No source publishes Open Queue rates, so META
is Competitive Role Queue on console (Americas), stated on every snapshot
fact rather than assumed away. Rates carry the patch and season they were
captured under, and the board warns when patches shipped since.
Judgements (counters, synergies, playstyles) are tier- and
region-agnostic by design, and a table is a table: every row carries its
source, and that is the only distinction drawn between measured, judged
and hand-written data. Only the strategies are hand-written. Players are assumed to play optimally - the ground
rule every skill holds a comp to ([skills.md](skills.md)), so a strategy
encodes the game, never a lobby's habits.
