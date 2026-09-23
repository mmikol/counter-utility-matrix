# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Countrix picks Overwatch 2 team compositions: a PostgreSQL database pulled
from Blizzard and the wiki, a board that turns every pick into numbered
facts, and a deterministic solver over a markdown playbook. Python 3.12:
`http.server` for the served layers, requests and beautifulsoup4 for the
scrapers, psycopg (pgserver for the embedded cluster), no web framework, no
JS build step. The docs are
the reference - [docs/architecture.md](docs/architecture.md) first, then one
doc per layer. This file is what a session needs before it changes code.

## Commands

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/ruff check db ui inference tests scripts orchestrator.py    # the paths CI lints

.venv/bin/python -m pytest -q -p no:cacheprovider --cov              # full suite, 75% bar, needs the built database
COUNTRIX_NO_DATABASE=1 .venv/bin/python -m pytest -q -rs -p no:cacheprovider --cov --cov-fail-under=0   # as CI runs it
.venv/bin/python -m pytest -q tests/test_docs.py                     # one file
.venv/bin/python -m pytest -q 'tests/test_docs.py::test_the_overview_names_everything_at_the_root'   # one test
.venv/bin/python -m pytest -q -m 'not invariant'                     # everything that needs no database

.venv/bin/python -m db.mcp call db_rebuild      # build the database: the embedded cluster at db/psql/cluster
.venv/bin/python -m db.mcp call db_migrate      # apply new migrations in place, keeping the data
.venv/bin/python -m db.mcp list                 # the MCP tools; `call <tool> '<json>'` runs one in-process
.venv/bin/python -m db.mcp call db_docs         # regenerate every generated doc section (needs the database)
.venv/bin/python -m ui.board --port 8018        # the board, engine in-process (8017 is the compose board)
.venv/bin/python orchestrator.py up|test|status|down   # the Docker stack; `up` rebuilds the image `test` runs in
```

A bare `orchestrator.py` is `run`: `up`, then the headless `claude -p /refresh`
agents, which refetch the sources and may tune the playbook. Pulls and
`db_rebuild` read the page caches, which keep a page forever; `'{"refresh":
true}'` refetches everything from the network, minutes at the polite pace.

Tests marked `invariant` need the database and skip without one, through
the `db` fixture - except `test_health_reports_the_catalog_and_the_database`,
which calls `default_dsn()` and boots the cluster even under
`COUNTRIX_NO_DATABASE=1`. The suite targets `db/psql/cluster` whenever that
folder exists; `DATABASE_URL` or `./docker-db <command>` points at another
Postgres. CI sets no variable: it has no cluster and no pgserver. An exported
`COUNTRIX_READ_ONLY=0` fails the suite, which pins the board read-only.

The solver spawns `max(6, min(cores, 12))` worker processes (12 here) in any
process that calls `engine.board()` without a catalog of its own: `ui.board`
and `inference.serve` at launch, the stdio MCP server and `db.mcp call board`
on the first board, pytest on the first board test. `COUNTRIX_WORKERS=6` is the lowest cap that keeps that test green;
`COUNTRIX_PARALLEL=0` solves in-process. Both are read at import. The pool
is spawn-context: killing the parent leaves `spawn_main` workers orphaned
under launchd, so stop them too.

Without the database, two generated sections regenerate on their own:
`.venv/bin/python -c "from db.mcp import tools; tools.write_tool_docs()"`
(docs/mcp.md) and
`.venv/bin/python -c "from inference import catalog; catalog.write_docs(catalog.load())"`
(the catalog in docs/inference.md). The second writes nothing while
`COUNTRIX_STRATEGIES` names another playbook folder - that variable picks the
playbook in force, relative to the repo root, and is read on every call.

## Architecture

Three layers over one database, each a folder: `db/` (DATA), `ui/` (FACTS),
`inference/` (STRATEGIES and the argmax).

- **One door for writes.** Every write to Postgres or the playbook is a tool
  registered with `@tool(...)` in `db/mcp/tools.py`, reached over stdio, HTTP
  or in-process (`tools.run_tool`), and every call is audited to
  `db/raw/audit.jsonl` - except the sentry, which renames a bad strategy file
  to `.md.quarantined` outside the door. Reads bypass the door: `ui/` and `inference/` connect
  through `db.psql.default_dsn()` - `DATABASE_URL`, else the embedded
  pgserver cluster, which starts on first touch.
- **One definition per metric.** `ui/facts/compute.py` defines every metric
  in a registry. The facts engine words them as facts, the solver scores the
  same functions, and the catalog validates a strategy's `metric` against the
  registry, so the number on the board and the number the solver maximises
  cannot drift. `ui/facts` is a shared library: `inference/` and
  `db/mcp/tools.py` import it.
- **Facts are numbered.** `FactSet` numbers facts F1.. and the playbook's
  record S1.. in emission order; a solver contribution cites a fact by metric
  key (`also=` on `FactSet.add`). Adding a fact renumbers every later id.
- **The playbook is markdown.** `inference/strategies/*.md` - the filename is
  the id; frontmatter sets the kind (constraint, heuristic, assumption). The
  form is derived, never written: limit (`require:`), scored
  (`bonus:`/`penalty:`), heuristic (`metric:`), assumption, or draft (name,
  kind and prose only). `inference/catalog.py` parses
  and validates it; one bad file makes `catalog.load` raise everywhere. The
  shipped playbook is five assumptions and nothing scored, on purpose, while
  it is rebuilt rule by rule from the citation record in
  `inference/README.md`. Solver behaviour is tested against the 19-file
  reference playbook in `tests/fixtures/playbook/`.
- **The solver is deterministic.** `engine.board()` returns a Board of up to
  seven Results (blue, red, current, red_current, fill, countered, expected);
  fill is None unless one to five blue picks are locked, countered is None
  without blue picks. Each seat has one scale: reference sixes drawn from a
  string seed, the map and the side, bounded against the enemy. current
  shares blue's optimal's scale, red_current red's, so within a seat infer,
  evaluate and current are comparable. Only `board()` uses the process pool,
  and the pooled and sequential answers must agree bit for bit: string-seeded
  RNGs, integer tallies, ties broken by `map_win_mean` and then sorted names.
- **The board** (`ui/board.py`) serves `/api/facts` in-process and delegates
  `/api/infer` and `/api/strategies` to `INFERENCE_URL` when set. It is read-only unless
  `COUNTRIX_READ_ONLY=0`; its one write is a `tune` call through the door.
- **Docker** runs one image as five roles plus postgres (`compose.yaml`,
  `docker-entrypoint.sh`). Migrations ship in the image, not a mount: once
  `orchestrator.py up` rebuilds it, any new migration file makes the `data`
  container `db_rebuild` on start, which drops the dated rates history.

## What the tests hold you to

`tests/test_docs.py` and friends fail on ordinary changes. Before committing:

- A new tracked file or folder at the root must be named in
  `docs/architecture.md` - a file in The files, a folder in The folders. The
  test greps the whole doc for the name.
- Every `os.environ.get("COUNTRIX_...")` in `db/`, `ui/`, `inference/` or
  `orchestrator.py` must appear in docs/architecture.md or docs/db.md.
- Text between `<!-- generated:NAME -->` markers is rendered from code and
  compared with a fresh render. Never edit it by hand; change the source
  (a `@tool` description, strategy frontmatter, a migration comment) and
  regenerate.
- Adding or renaming an MCP tool: regenerate docs/mcp.md; the backticked tool
  names in `.claude/skills/refresh/SKILL.md` must equal
  `orchestrator.AGENT_TOOL_NAMES`; each house skill must still name the tools
  `MUST_NAME` (tests/test_docs.py) lists; tests/db/test_mcp.py holds the tool
  set too.
- A new strategy file is cited as a ``- `id` `` line in `inference/README.md`.
- A new table carries `source_id` and `cao`, has rows, is exported to
  `db/raw` (`export_csv`) and is named in `ui/facts/model.py` (a test greps
  its source); regenerate the schema sections of docs/db.md. Its migration
  also wants a `schema.DOC_DOMAIN` entry keyed by filename, or docs/db.md
  files it under foundation - no test catches that one.
- A new metric: an entry in `TEAM_METRICS`, `MATCHUP_METRICS`, `MAP_METRICS`
  or `WORLD_METRICS` and the key its function computes (the namespace must
  equal the registry), `TEXT_METRICS` or `VERSUS_KEYS` or `RED_MATCHUP` where
  they apply, then regenerate the catalog vocabulary in docs/inference.md.
- `tests/ui/test_board.py` asserts literal source text in `ui/static/*.js`
  and `math.html`, and that every `board.css` class is used. The math page
  restates code constants (`SYNERGY_PULL`); change both with the test.
- `tests/fixtures/optimal.json` is the regression gate on the search.
  Regenerate it only after a deliberate change to the objective: re-run the
  brute force (it lives outside the repo), then `OPTIMAL_SOURCES=<its .jsonl
  files> .venv/bin/python scripts/optimal.py`, which records proofs and
  computes none. Say in the commit why every number moved.

## House rules

- A session never hand-edits the playbook. Changes go through `tune`,
  `add_strategy`, `infer_strategy` or `derive_strategies` (`load_authored`
  also derives drafts where the claude CLI is signed in). They validate,
  rewrite the docs catalog for the shipped playbook and append a reasoned
  line to `tuning-log.md` beside the playbook in force. A draft the user drops
  in by hand (name, kind, prose) is input; the tools fill its frontmatter.
  Called without `directory=`, `tune`/`add`/`complete` rewrite the live
  playbook, so tests pass a temporary copy.
- Migrations are `db/psql/migrations/NNN_name.sql`; new ones wrap in
  `BEGIN;`/`COMMIT;` (010-013 do not, and `schema.apply` commits after each
  file either way). The ledger records filenames only: never edit an
  applied migration, add the next number. Locally, `db_migrate` keeps the
  data; `db_rebuild` drops it.
- Over stdio, stdout is the JSON-RPC wire. Code reachable from a tool logs
  through `ctx.log` or stderr, never `print`. A refusal raises `ToolError`.
- SQL identifiers go through `db.psql.identifier()`; values are always
  parameters.
- Pulls read only Blizzard's site and the wiki, through the page caches,
  each at its own pace: `fetch.cached_get` for Blizzard pages, 5 s for the
  rates (`db/data/blizzard/meta.py`), the wiki's own client with a 0.5 s delay
  and rate-limit backoff (`db/data/wiki/__init__.py`). No third source, no
  API keys.
- `.venv/bin/python -m db.sentry --once` is not read-only: it renames a
  suspect strategy file to `.md.quarantined`.
- Never `docker compose down -v`: it deletes the database volume.

## Style

- `%`-formatting, never f-strings or `.format()` (ruff's UP031/UP032 are off
  for this).
- Public functions carry full type annotations, and records that cross a
  module boundary are dataclasses or TypedDicts rather than ad-hoc dicts and
  tuples. This replaces the older seams-only rule; code is converging on it.
- Every module opens with a docstring saying what it does. Test names are
  declarative sentences (`test_the_overview_names_everything_at_the_root`);
  side effects are stubbed with `monkeypatch`, not mocks.
- Prose in docs, comments, skills and commits is terse, declarative, present
  tense and ASCII, with a spaced hyphen where a dash would go. Headings name
  things with the definite article ("The files"). Non-ASCII is kept to math
  notation, the middle-dot separator, accented hero names and the board's
  glyphs (the ban cross, the ellipsis). `.claude/skills/desloppify/SKILL.md`
  is the tool's own text: leave it as `update-skill` writes it.
- Commit subjects state the outcome as a sentence, no type prefix, no period
  ("The scale holds still under bans"). The body says why, in prose wrapped
  near 72 columns, with measured numbers such as the test count.
- `pm/backlog.md` is the payoff-ordered backlog; `/maintain` keeps it and the
  docs current and records what the checks missed under its Lessons learned.

## Desloppify

The desloppify harness scores the code and drives the cleanup loop. It is
not in requirements.txt, so CI and the image stay lean; install it into the
venv and restore its local config, which lives in the gitignored
`.desloppify/`:

```bash
.venv/bin/pip install --upgrade "desloppify[full]"
.venv/bin/desloppify update-skill claude        # refreshes .claude/skills/desloppify/SKILL.md
for p in .venv .cache-blizzard .cache-wiki db/psql/cluster db/raw; do .venv/bin/desloppify exclude $p; done
.venv/bin/desloppify config set target_strict_score 98
```

The loop: `.venv/bin/desloppify scan --path .`, then `next`, fix, `plan
resolve <id> --attest "I have actually ... not gaming ..."` (`next` prints
the exact command), repeat; `status` shows the scores. Follow the scan's own
instructions. Its commits follow the house style above, not its
`desloppify: ...` template.
