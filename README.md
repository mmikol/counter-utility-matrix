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

Everything is free to run - no accounts, no keys. The one optional paid
feature is the final model opinion (see "The paid button" below).

## Install & run (Docker - recommended)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(or any docker + compose v2). Then:

```bash
git clone git@github.com:mmikol/overwatch-db.git
cd overwatch-db
cp .env.example .env      # fine to leave as is - the key is optional
docker compose up
```

The first run builds the database from scratch - migrations, then every
pipeline, scraping the sources once (a few polite minutes; page caches land
in `.cache-*/` so later builds cost almost no requests). Then the UI serves
at **http://localhost:8017**: a dashboard of the whole database, and an
"ask for a comp" form whose *evidence preview* shows the ~90-140 cited lines
the model would reason over - free, no key.

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
cp .env.example .env
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

## The paid button

The **Recommend (calls Claude)** button / `recommend.py` sends the evidence
dossier to the Anthropic API - billed per token at
[console.anthropic.com](https://console.anthropic.com); a Claude subscription
does **not** cover it. With `ANTHROPIC_API_KEY` blank, the app says so
politely and everything else works. With a key: Claude Fable 5.1 at maximum
reasoning by default (`OVERWATCH_DB_MODEL` / `OVERWATCH_DB_EFFORT` in `.env`
dial cost down), server-side refusal fallbacks enabled, and every stored
recommendation records the full prompt, the evidence cited per pick, and
which model actually answered.

## Layout

```
orchestrator.py      the conductor: verbs, shared plumbing, docs generation
ui.py                local UI (stdlib only) - dashboard + recommend form
data/
  sources/           where scraped data comes from (blizzard, wiki, counterpick)
  authoritative/     what a source measured    extract -> transform -> load
  heuristic/         what a source judges      extract -> transform -> load
  proprietary/       what WE judge: authored CSVs (synergies, archetypes,
                     map_playstyle, seasons), strategy notes, the dossier
                     and recommend inference layer, and its transcripts
  raw/               one CSV per table (exported, gitignored)
db/
  migrations/        001 sources · 002 heroes · 003 maps · 004 meta ·
                     005 playbook · 006 inference
  cluster/           the locally built database (gitignored; Docker uses a
                     postgres service instead)
docs/                erd.md · data-dictionary.md · scaling.md - the first two
                     are generated: python -m orchestrator docs
tests/               82 tests: unit, invariants, export parity, validation
```

## Documentation

- [docs/erd.md](docs/erd.md) - entity relationships, by domain and whole-db
- [docs/data-dictionary.md](docs/data-dictionary.md) - every table & column, generated from the live schema
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
