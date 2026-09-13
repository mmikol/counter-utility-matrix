# overwatch-db

[![ci](https://github.com/mmikol/overwatch-db/actions/workflows/ci.yml/badge.svg)](https://github.com/mmikol/overwatch-db/actions/workflows/ci.yml)

An exploration into optimizing Overwatch team compositions, built as three
layers over one PostgreSQL database:

```
DATA LAYER        an MCP server pulls every source, cleans it, stores it
USER LAYER        a map + red/blue hero-select board that turns every click
                  into FACTS pulled from the database
INFERENCE LAYER   markdown heuristics (constraints, goals, strategies)
                  scored over those facts to find the optimal composition
```

```
FACTS = HEROES ∪ MAPS ∪ META ∪ PLAYBOOK ∪ HISTORY     the whole database, for one board
COMP  = ARGMAX[ STRATEGIES( FACTS ) ]                  constraints prune, goals weigh,
                                                       strategies adjust; the agent argues
```

The user layer turns every table into facts for the board in front of you;
the inference layer scores those facts under the heuristics (constraints,
goals, strategies) and searches for the argmax; the inference agent - a
Claude Code session on the `/comp` skill - reads the same facts and the
same strategies and reconciles them where arithmetic cannot.

Everything is free to run - no accounts, no keys, no API billing. The
board is a local page; the inference layer is deterministic; the chat
front (`/comp`) runs inside a Claude Code session on your subscription.

## Install & run (Docker - recommended)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(or any docker + compose v2). Then:

```bash
git clone git@github.com:mmikol/overwatch-db.git
cd overwatch-db
docker compose up --build
```

One container per layer, from one image:

| container | layer | serves |
| --- | --- | --- |
| `db` | the database | PostgreSQL 16 (host port 5433 for `./docker-db`) |
| `data` | DATA LAYER | builds the database when empty or stale, then the MCP server over HTTP at **http://localhost:8020/mcp** |
| `inference` | INFERENCE ENGINE | **http://localhost:8019** - `/infer`, `/evaluate`, `/heuristics`, `/record`, `/health` |
| `ui` | USER LAYER | the **board** at **http://localhost:8017** |
| `refresher` | the data layer's clock | refreshes everything daily (see below) |

The first run builds the database from scratch (migrations, every pull
tool, the authored playbook - a few polite minutes; page caches land in
`.cache-*/` so later builds cost almost no requests); `inference` and `ui`
wait for it, and `docker compose ps` shows all four healthy. A schema
change rebuilds automatically (the migrations ledger), with recorded comps
restored from the `data/raw` mirror. Edits to `inference/heuristics/`,
`data/proprietary/` and the caches are bind-mounted, so they apply without
a rebuild. Upgrading an install that predates the per-layer stack: add
`--remove-orphans` once to retire the old single `app` container. Other
things to run in the same image:

```bash
docker compose run data python -m data.orchestrator update     # refresh the data
docker compose run data python -m data.mcp call infer '{"map": "King'"'"'s Row", "red": ["Zarya"]}'
docker compose run data pytest -q
docker compose logs -f data                               # watch a build
docker compose down
```

## Install & run (local, no Docker)

Requires Python 3.9+ (no PostgreSQL install needed - `pgserver` embeds one;
macOS and Linux x86_64):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m data.orchestrator rebuild     # build the database
.venv/bin/python -m user.board                       # the board, http://localhost:8017
.venv/bin/python -m pytest -q                # the test suite
```

## Keeping it fresh

The `refresher` container refreshes the whole database once a day, so the
board is ready when a game starts: every page of every source is fetched
again, entities are upserted in place, the rates append a new dated
snapshot (the series the trend facts difference), the authored playbook and
the heuristics files are re-mirrored, and `data/raw` is re-exported. It
also refreshes right away on start when the cached pages are older than a
day. A page that fails to fetch keeps its cached copy, so a flaky source
degrades to yesterday's numbers rather than an empty table; the board's
header shows the capture date and warns when patches shipped since.

| setting | default | meaning |
| --- | --- | --- |
| `OVERWATCH_DB_REFRESH_AT` | `05:00` | daily time, in the container's `TZ` (UTC unless set) |
| `OVERWATCH_DB_REFRESH_MAX_AGE_HOURS` | `20` | refresh on start when the cache is older than this |

Set them in the environment or a `.env` file next to `compose.yaml`. The
same refresh from a shell, against whichever database `DATABASE_URL` names:

```bash
.venv/bin/python -m data.refresh --now        # once, now
.venv/bin/python -m data.refresh              # the daily loop
.venv/bin/python -m data.mcp call sync_all '{"refresh": true}'
```

## The data layer: an MCP server

`data/mcp/` is a [Model Context Protocol](https://modelcontextprotocol.io) server
(dependency-free) that exposes the pulling, cleaning and storing of every
source as tools, over stdio for a local build and over Streamable HTTP
from the `data` container. Open the repo in a Claude Code session and
`.mcp.json` registers both - `overwatch-db` (stdio, the local cluster) and
`overwatch-db-docker` (`http://localhost:8020/mcp`, the compose database);
the session can then say "refresh the rates" and call `pull_rates`, or ask
`query` for any SQL. Nothing is a static script: a session, the
orchestrator, or cron decides what to pull and when.

| tool | does |
| --- | --- |
| `pull_heroes` · `pull_kits` · `pull_maps` · `pull_patches` · `pull_rates` · `pull_playstyles` · `pull_counters` | one source and domain each: fetch (cached), clean, upsert |
| `load_playbook` | the authored inputs: seasons, strategy notes, synergies, archetypes, map playstyles, and the mirror of the heuristics files |
| `sync_all` | all of the above in dependency order, then the CSV mirror; `refresh: true` fetches every page again |
| `db_status` · `db_init` · `db_rebuild` · `export_csv` · `db_docs` · `query` | the database's life, and read-only SQL |
| `roster` · `facts` · `infer` · `evaluate` · `heuristics` · `record` | the user and inference layers through the same door |

The same tools run from a shell (`python -m data.mcp call pull_maps`) and are
what `python -m data.orchestrator` drives:

| command | does |
| --- | --- |
| `python -m data.orchestrator rebuild` | clean slate: schema + every tool + restore recorded comps |
| `python -m data.orchestrator` | update (default): entities refresh in place, rates append a snapshot |
| `python -m data.orchestrator init` / `inflate` | schema only / first fill |
| `python -m data.orchestrator export` / `docs` | refresh `data/raw/*.csv` / regenerate the generated docs |
| `--only pull_rates`, `--refresh` | one tool; discard the page cache first |

## The user layer: the board

`user/board.py` serves a map selector and two hero-select screens - red for the
enemy, blue for you - organised by role with the game's own portraits and
role icons. Every click re-reads the database and rebuilds the **facts**:
100+ independent facts per named hero (kit numbers, keywords, perks, rates
by rank and map, counters, partners), the map's own facts, joint facts per
team once it has picks (shape, effective HP, damage and healing floors,
burst ceiling, range and cooldown profiles, crowd control, mobility,
barriers, cohesion, availability, map fit, coverage of the other team) and
matchup facts once both teams do (pool and floor differentials, burst vs
heal, chew time, tempo and poke wars, net answer edges, dive pressure,
vertical threats, the ult race). Every fact is numbered `F1..` and cites
its table or formula; `user/facts/compute.py` is the registry of every metric.

## The inference layer: heuristics in markdown

`inference/heuristics/` holds one file per heuristic - frontmatter a
machine scores by, prose a person argues with:

```markdown
---
name: Answer every revealed enemy
kind: goal                # constraint | goal | strategy
category: matchup
direction: maximize
metric: team.coverage_share
weight: 3
when: enemy.size >= 1
---
# Answer every revealed enemy
The share of revealed enemies at least one of our picks answers...
```

The solver keeps the locked blue picks, enumerates the rest of the six
from per-role pools (6v6 Open Queue: any mix, at most two tanks - the one
constraint shipped), prunes with the constraints, normalises each goal
across the candidates, adds the scored strategies, and refines the best
few by local search -
players assumed to play optimally, so the score is a comp's ceiling. The
board's **optimal comp** panel shows the six with per-pick reasons and
fact citations, the score broken down per heuristic, and alternatives;
with six blue picks locked it evaluates yours against the field instead.
Tuning is editing a file; the catalog is validated on load and rendered
to [docs/heuristics.md](docs/heuristics.md). The engine runs in-process
for a local board and as its own service (`python -m inference.serve`,
the `inference` container) when the board is given `INFERENCE_URL`.

## Chat with it

Open this repo in a [Claude Code](https://claude.com/claude-code) session and
ask - "comp for King's Row, they have Zarya and Pharah, I'm on Ana". The
`/comp` skill calls the MCP server's `infer` and `facts` tools, argues
against the solver's optimum under the strategy heuristics, answers with
per-pick citations, and records the result through `record` - so session
comps become part of the database's own history. No API key, no per-token
bill. With the compose stack up, the `overwatch-db-docker` server reaches
the same database the board shows; for shell commands, prefix
`./docker-db`.

## Layout

The tree is the three layers:

```
data/                DATA LAYER - pulls, cleans, stores; owns the schema
  mcp/               the MCP server: server.py (stdio + HTTP), tools.py (the tools)
  orchestrator.py    the conductor: verbs over the same tools (Docker, a shell)
  refresh.py         the daily refresh (the `refresher` container)
  sources/           where pages come from (blizzard, wiki, counterpick), cached
  authoritative/     what a source measured   extract -> transform -> load (run())
  heuristic/         what a source judges     extract -> transform -> load (run())
  proprietary/       what WE author: CSVs, strategy notes, recorded transcripts
  db/                migrations/ (001 sources · 002 heroes · 003 maps · 004 meta ·
                     005 playbook · 006 inference · 007 three layers · 008 the
                     ledger), schema.py, cluster/ (the local build, gitignored)
  common.py          the plumbing every layer shares
  raw/               one CSV per table (exported, gitignored)
user/                USER LAYER - every click becomes facts
  facts/             model.py (the World), compute.py (the metrics registry),
                     engine.py (the FactSet)
  board.py           the map selector and the red and blue rosters
inference/           INFERENCE LAYER - facts in, the optimal six out
  heuristics/        one markdown file per heuristic (the brain)
  catalog.py         reads, validates, mirrors and documents the heuristics
  expr.py            the safe expression language the frontmatter uses
  solver.py          enumerate · prune · normalise · refine
  engine.py          infer() and evaluate(), with fact citations
  record.py          the storage gates and the transcript
  serve.py           the engine as a service (the `inference` container)
tests/               mirrored: tests/data · tests/user · tests/inference
compose.yaml         one container per layer: db · data · inference · ui · refresher
Dockerfile           one image for all of them; docker-entrypoint.sh picks the role
docs/                architecture.md · heuristics.md · erd.md · data-dictionary.md
```

## Documentation

- [docs/architecture.md](docs/architecture.md) - **start here**: the three layers in diagrams
- [docs/heuristics.md](docs/heuristics.md) - the catalog, how scoring works, and every metric a heuristic may reference (generated)
- [docs/erd.md](docs/erd.md) · [docs/data-dictionary.md](docs/data-dictionary.md) - the schema (generated)
- [docs/scaling.md](docs/scaling.md) - how region/rank/platform/stage granularity widens
- [data/proprietary/README.md](data/proprietary/README.md) - the authored inputs

## Scope, honestly

Open Queue Competitive is the goal; no source publishes Open Queue rates,
so META is Competitive Role Queue on console (Americas), stated on every
snapshot fact rather than assumed away. Rates carry the patch and season
they were captured under, and the board warns when patches shipped since.
Judgements (counters, synergies, playstyles) are tier- and region-agnostic
by design. Players are assumed to play optimally - the central assumption,
named in [inference/heuristics/optimal-play.md](inference/heuristics/optimal-play.md).
