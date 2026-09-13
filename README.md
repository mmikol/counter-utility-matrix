# overwatch-db

[![ci](https://github.com/mmikol/overwatch-db/actions/workflows/ci.yml/badge.svg)](https://github.com/mmikol/overwatch-db/actions/workflows/ci.yml)

This is an exploration into optimizing team composition strategies. Beginning
first with data and an API that is more robust than existing options.

A normalized PostgreSQL database of Overwatch gameplay - heroes, kits and
their numbers, maps and stages, win/pick/ban rates delineated by patch and
season, and a playbook of counters, synergies and playstyles - scraped from
public sources by four-stage pipelines, plus an inference layer that turns it
all into cited team-composition recommendations:

```
COUNTER = MAX[ HEROES ∩ MAPS ∩ META ]
```

Everything is free to run - no accounts, no keys, no API billing.
Compositions come from chatting: open the repo in a Claude Code session and
ask (the `/comp` skill turns the session into the agent - it reads the
evidence, decides, cites, and records).

## Install & run (Docker - recommended)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(or any docker + compose v2). Then:

```bash
git clone git@github.com:mmikol/overwatch-db.git
cd overwatch-db
docker compose up
```

The first run builds the database from scratch - migrations, then every
pipeline, scraping the sources once (a few polite minutes; page caches land
in `.cache-*/` so later builds cost almost no requests). Then the UI serves
at **http://localhost:8017**: a dashboard of the whole database, a **live
evidence board** built for use during a match - click heroes onto their
team and yours as picks reveal themselves, choose the map, and the ~190
cited lines a comp decision rests on rebuild on every click, including the
`derived:` analytics the database computes itself (role-shape flags,
healing supply, coverage, net matchup, draft skeletons; the 100-formula
catalog in docs/heuristics.md, tunable via the playbook). The board
survives reloads mid-game and surfaces any comp the /comp skill records
while you play. A viewer shows every recorded recommendation with its
citations.

Every later `docker compose up` skips straight to serving (the database
persists in a named volume). Other things to run in the same image:

```bash
docker compose run app python -m orchestrator update    # refresh the data
docker compose run app python -m data.proprietary.recommend \
    --map "King's Row" --enemy Zarya --ask "we keep losing the first fight"
docker compose run app pytest -q                        # the test suite
docker compose down                                     # stop everything
```

## Install & run (local, no Docker)

Requires Python 3.9+ (no PostgreSQL install needed - `pgserver` embeds one;
macOS and Linux x86_64):

```bash
git clone git@github.com:mmikol/overwatch-db.git
cd overwatch-db
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m orchestrator rebuild     # build the database
.venv/bin/python ui.py                       # serve http://localhost:8017
.venv/bin/python -m pytest -q                # 82 tests against the build
```

The orchestrator's verbs, each refusing the state it is not for:

| command | does |
| --- | --- |
| `python -m orchestrator rebuild` | clean slate: schema + every pipeline + CSVs |
| `python -m orchestrator` | update (default): refresh entities, append a dated snapshot |
| `python -m orchestrator init` / `inflate` | schema only / first fill |
| `python -m orchestrator export` / `docs` | refresh `data/raw/*.csv` / regenerate the ERD & data dictionary |
| `--type heuristic`, `--only authoritative.wiki.maps` | partial updates |

## Chat with it

Open this repo in a [Claude Code](https://claude.com/claude-code) session and
just ask - "comp for King's Row, they have Zarya and Pharah". The `/comp`
skill (in `.claude/skills/`) makes the session the inference layer: it runs
the evidence dossier, reasons under the same ground rules every time, answers
with per-pick citations, and records the result through the same validation
gates and tables - so session comps become part of the database's own history
evidence. Covered by a Claude subscription; no API key, no per-token bill.

Chatting against the Docker database instead of a local build: prefix
commands with the bridge script, e.g.
`./docker-db .venv/bin/python -m data.proprietary.dossier --map Ilios` -
the skill knows to do this.

## Layout

```
orchestrator.py      the conductor: verbs, shared plumbing, docs generation
ui.py                local UI (stdlib only) - dashboard + recommend form
data/
  sources/           where scraped data comes from (blizzard, wiki, counterpick)
  authoritative/     what a source measured    extract -> transform -> load
  heuristic/         what a source judges      extract -> transform -> load
  proprietary/       what WE judge: authored CSVs (synergies, archetypes,
                     map_playstyle, seasons), strategy notes, the evidence
                     dossier, the recommendation store, and its transcripts
  raw/               one CSV per table (exported, gitignored)
db/
  migrations/        001 sources · 002 heroes · 003 maps · 004 meta ·
                     005 playbook · 006 inference
  cluster/           the locally built database (gitignored; Docker uses a
                     postgres service instead)
docs/                erd.md · data-dictionary.md · scaling.md - the first two
                     are generated: python -m orchestrator docs
tests/               108 tests: unit, invariants, export parity, UI, validation
```

## Documentation

- [docs/architecture.md](docs/architecture.md) - **start here**: the whole machine in five diagrams - sources to pipelines to Postgres to dossier to the /comp skill and back
- [docs/erd.md](docs/erd.md) - entity relationships, by domain and whole-db
- [docs/data-dictionary.md](docs/data-dictionary.md) - every table & column, generated from the live schema
- [docs/heuristics.md](docs/heuristics.md) - the 100-consideration catalog behind the `derived:` evidence lines, stored and tuned in the playbook
- [docs/scaling.md](docs/scaling.md) - how region/rank/platform/stage granularity widens
- [data/proprietary/README.md](data/proprietary/README.md) - the authored inputs and the inference layer

## Scope, honestly

Open Queue Competitive is the goal; no source publishes Open Queue rates, so
META is Competitive Role Queue on console (Americas), stated on every
snapshot rather than assumed away. Rates carry the patch and season they
were captured under. Judgements (counters, synergies, playstyles) are
tier- and region-agnostic by design. `synergies`, `comp_archetypes`,
`map_playstyle` and the strategy notes are hand-authored in
`data/proprietary/` - edit the files, rerun `update`, and the tables mirror
them exactly.
