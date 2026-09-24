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

.venv/bin/ruff check db facts inference door ui tests scripts orchestrator.py   # the paths CI lints
.venv/bin/python -m mypy db facts inference door ui orchestrator.py scripts     # the types CI checks

.venv/bin/python -m pytest -q -p no:cacheprovider --cov                         # full suite, 75% bar, needs the built database
COUNTRIX_NO_DATABASE=1 .venv/bin/python -m pytest -q -rs -p no:cacheprovider --cov --cov-fail-under=78   # as CI runs it
.venv/bin/python -m pytest -q tests/test_docs.py                                # one file
.venv/bin/python -m pytest -q 'tests/test_docs.py::test_the_overview_names_everything_at_the_root'   # one test
.venv/bin/python -m pytest -q -m 'not invariant'                                # everything that needs no database

.venv/bin/python -m door.mcp call db_rebuild      # build the database: the embedded cluster at db/psql/cluster
.venv/bin/python -m door.mcp call db_migrate      # apply new migrations in place, keeping the data
.venv/bin/python -m door.mcp list                 # the MCP tools; `call <tool> '<json>'` runs one in-process
.venv/bin/python -m door.mcp call db_docs         # regenerate every generated doc section (needs the database)
.venv/bin/python -m ui.board --port 8018          # the board, engine in-process (8017 is the compose board)
.venv/bin/python orchestrator.py up|test|status|down   # the Docker stack; `up` rebuilds the image `test` runs in
```

A bare `orchestrator.py` is `run`: `up`, then the headless `claude -p /refresh`
agents, which refetch the sources and may tune the playbook. Pulls and
`db_rebuild` read the page caches, which keep a page forever; `'{"refresh":
true}'` refetches everything from the network, minutes at the polite pace.

Tests marked `invariant` need the database and skip without one, through
the `db` fixture. The suite targets `db/psql/cluster` when that
cluster is built and `DATABASE_URL` is unset; `DATABASE_URL` or
`./docker-db <command>` points it at another Postgres. CI sets no
variable: it has no cluster and no pgserver.

The solver's pool (`inference/parallel.py`) spawns `max(6, min(cores, 12))`
worker processes (12 here) in any process that calls `engine.board()`
without a catalog of its own: `ui.board`
and `inference.serve` at launch, the stdio MCP server and `door.mcp call board`
on the first board, pytest on the first board test. `COUNTRIX_WORKERS=6` is
the lowest cap that keeps that test green; `COUNTRIX_PARALLEL=0` solves
in-process. `COUNTRIX_PARALLEL` is read on every board, `COUNTRIX_WORKERS`
when the pool starts. The pool is spawn-context, and a worker exits within
a second of its parent, a kill included.

Without the database, two generated sections regenerate on their own:
`.venv/bin/python -c "from door.mcp import tools; tools.REGISTRY.write_docs()"`
(docs/mcp.md) and
`.venv/bin/python -c "from inference import catalog; catalog.write_docs(catalog.load())"`
(the catalog in docs/inference.md). The second writes nothing while
`COUNTRIX_STRATEGIES` names another playbook folder - that variable picks the
playbook in force, relative to the repo root, and is read on every call.

## Architecture

Three layers over one database, each a folder at the root: `db/` (DATA),
`facts/` (FACTS), `inference/` (STRATEGIES and the argmax). `ui/` is the
board over them, and `door/` stands over all three. Imports run
db <- facts <- inference <- door <- ui.

- **One door for writes.** Every write to Postgres or the playbook runs
  under a tool. Each family module (`pulls`, `lifecycle`, `facts`, `solver`,
  `playbook` in `door/mcp/`) declares its tools with `@tool(...)` into the
  one `REGISTRY` (`door/mcp/registry.py`), which lists them in `FAMILIES`'
  order, and `door/mcp/tools.py` imports every family. A call arrives over
  stdio, HTTP or in-process (`ctx.call`), is checked against the
  tool's schema by the same `Tool` wrapper on every path, and is audited to
  `db/raw/audit.jsonl` - except the sentry, which renames a bad strategy
  file to `.md.quarantined` outside the door. The code that writes lives
  with what it writes - the pulls in `db/data`, the strategies table in
  `inference.catalog.mirror`, the playbook's files in `inference.tune` - and
  only the tools call it. Reads bypass the door: the board, `facts/` and
  `inference/` read through `db.psql.default_dsn()` - `DATABASE_URL`, else
  the embedded pgserver cluster at `db/psql/cluster`, started on first
  touch; only db_init and db_rebuild create it (`psql.boot`), and a read
  with neither raises `psql.NoDatabaseError`.
- **One definition per metric.** `facts/team.py` defines every team
  metric and `facts/compute.py` the matchup, map and world ones, each in a
  registry, and `compute.registry()` gathers them. The facts engine words
  them as facts, the solver scores the same functions, and the catalog
  validates a strategy's `metric` against the registry, so the number on the
  board and the number the solver maximises cannot drift. `facts/` is a
  shared library: `inference/`, the door's `facts`, `solver`, `boards` and
  `playbook` modules, the board and `scripts/reach.py` import it.
- **Facts are numbered.** `FactSet` numbers facts F1.. and the playbook's
  record S1.. in emission order; a solver contribution cites a fact by metric
  key (`also=` on `FactSet.add`). Adding a fact renumbers every later id.
- **The playbook is markdown.** `inference/strategies/*.md` - the filename is
  the id; frontmatter sets the kind (constraint, heuristic, assumption). The
  form is derived, never written: limit (`require:`), scored
  (`bonus:`/`penalty:`), heuristic (`metric:`), assumption, or draft (name,
  kind and prose only). `inference/catalog.py` reads it, each file parsed
  by `frontmatter.py` and checked by `strategy.py` (`Strategy`,
  `CatalogError`); one bad file makes `catalog.load` raise everywhere. The
  shipped playbook is five assumptions and nothing scored, on purpose, while
  it is rebuilt rule by rule from the citation record in
  `inference/README.md`. Solver behaviour is tested against the 19-file
  reference playbook in `tests/fixtures/playbook/`.
- **The solver is deterministic.** `engine.board()` returns a Board of up to
  seven Results (blue, red, current, red_current, fill, countered, expected);
  fill is None unless one to five blue picks are locked, countered is None
  without blue picks or when the caller's `Brief` leaves it out, as the
  page's boards do. Each seat has one scale: reference sixes drawn from a
  string seed, the map and the side, bounded against the enemy. current
  shares blue's optimal's scale, red_current red's, so within a seat infer,
  evaluate and current are comparable. Only `board()` uses the process pool,
  and the pooled and sequential answers must agree bit for bit: string-seeded
  RNGs, integer tallies, ties broken by `map_win_mean` and then sorted names.
- **The board** (`ui/board.py`, its pages in `ui/pages.py`) serves
  `/api/facts` in-process and delegates `/api/board` and `/api/strategies` to
  `COUNTRIX_INFERENCE_URL` when set. It is read-only unless
  `COUNTRIX_READ_ONLY=0`; its one write is a `tune` call through the door.
  All three HTTP servers stand on `db/web.py`: a request whose Host or Origin
  is not a local name or one given with `--allow-host` is refused with 403.
- **Docker** runs one image as five roles plus postgres (`compose.yaml`,
  `docker-entrypoint.sh`). Migrations ship in the image, not a mount: once
  `orchestrator.py up` rebuilds it, any new migration file makes the `data`
  container `db_rebuild` on start, which drops the dated rates history.

## What the tests hold you to

`tests/test_docs.py` and friends fail on ordinary changes. Before committing:

- A new tracked file or folder at the root must be named in
  `docs/architecture.md` - a file in The files, a folder in The folders. The
  test greps the whole doc for the name.
- A new module, folder or file inside a package gets a line in the map of
  its package's `__init__.py` docstring: indented, the name, then two
  spaces or more before what it is (`.py` optional, a folder's slash too).
  A name that only opens a wrapped line of prose does not count.
- Every quoted `"COUNTRIX_..."` name in `db/`, `facts/`, `inference/`,
  `door/`, `ui/` or `orchestrator.py` must appear in docs/architecture.md
  or docs/db.md, and is read where it is used or by `main()` at start: an
  `os.environ`, `os.getenv` or `os.path.expanduser` (it reads HOME) that
  runs at import fails `test_no_module_reads_the_environment_at_import`.
- A new migration is named by its number in docs/db.md's `migrations/`
  row, the one inventory of the schema's steps. The whole chain must build
  an empty database: an invariant test applies it to a scratch database
  on the target server and compares the tables with the built one.
- Only a door tool in `door/mcp/` calls the playbook's writers -
  `catalog.mirror`, `tune.tune`/`add`/`complete`, `derive.derive` - and
  `inference/derive.py`, which completes drafts inside a run the door
  started. A new call site elsewhere fails the test; route it through a
  tool.
- Each layer imports only the layers below it: `db/` imports nothing above
  it, `facts/` only `db/`, `inference/` `db/` and `facts/`, `door/` all
  three; `ui/`, `scripts/` and `orchestrator.py` import any of them. An
  upward import, deferred or not, fails
  `test_each_layer_imports_only_the_layers_below_it`.
- A line indented 1 to 16 columns sits on a multiple of 4, docstring maps
  and SQL in strings included, and a continuation hangs 4 columns in after
  a bracket that ends its line (8 for a def's parameters). One line off the
  stop makes desloppify read the indent unit as 1 and count every column
  as nesting.
- Text between `<!-- generated:NAME -->` markers is rendered from code and
  compared with a fresh render. Never edit it by hand; change the source
  (a `@tool` description, strategy frontmatter, a migration comment) and
  regenerate.
- Adding or renaming an MCP tool: regenerate docs/mcp.md; the backticked tool
  names in `.claude/skills/refresh/SKILL.md` must equal
  `orchestrator.AGENT_TOOL_NAMES`; each house skill must still name the tools
  `MUST_NAME` (tests/test_docs.py) lists; tests/door/mcp/test_mcp.py holds the
  tool set too.
- A new strategy file is cited as a ``- `id` `` line in `inference/README.md`.
  A house skill or a doc names a strategy only by an id the playbook
  holds: a backticked id the record cites and `inference/strategies/`
  lacks is a dropped rule, and fails.
- A new table carries `source_id` and `cao`, has rows, is exported to
  `db/raw` (`export_csv`) and is named in `facts/tables.py` (a test greps
  its source); regenerate the schema sections of docs/db.md. Its migration
  also wants a `schema.DOC_DOMAIN` entry keyed by filename, or docs/db.md
  files it under foundation - no test catches that one.
- A new metric: an entry in `TEAM_METRICS`, `MATCHUP_METRICS`, `MAP_METRICS`
  or `WORLD_METRICS` and the key its function computes (the namespace must
  equal the registry), `TEXT_METRICS` or `VERSUS_KEYS` or `RED_MATCHUP` where
  they apply, then regenerate the catalog vocabulary in docs/inference.md.
- `tests/ui/test_pages.py` asserts literal source text in `ui/static/*.js`
  and `math.html`, and that every `board.css` class is used. The math page
  restates code constants (`SYNERGY_PULL`); change both with the test.
- `tests/fixtures/optimal.json` is the regression gate on the search.
  Regenerate it only after a deliberate change to the objective: re-run the
  brute force (it lives outside the repo), then `OPTIMAL_SOURCES=<its .jsonl
  files> .venv/bin/python -m scripts.optimal`, which records proofs and
  computes none. Say in the commit why every number moved. The fixture
  records its playbook's digest (`catalog.playbook_digest`), so the gate
  skips while the shipped playbook scores nothing and fails under any other
  playbook that scores; `.venv/bin/python -m scripts.reach` re-records
  `reach.json` the same way. Boards with bans are held out until they are
  re-proven (`pm/backlog.md`).

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
  file either way). The ledger records filenames only: never edit a
  statement in an applied migration, add the next number. The `--` prose
  is documentation the data dictionary reads, and is kept current.
  Locally, `db_migrate` keeps the data; `db_rebuild` drops it.
- Over stdio, stdout is the JSON-RPC wire. Code reachable from a tool logs
  through `ctx.log` or stderr, never `print`. A refusal raises `db.Refusal`;
  anything else is the server's fault.
- A table or column name reaches SQL only as the `psycopg.sql.Identifier`
  that `db.psql.identifier()` returns, composed with `psycopg.sql.SQL`;
  values are always parameters.
- Pulls read only Blizzard's site and the wiki, through the page caches and
  the one request loop in `db/data/fetch.py`, each at the pace of its own
  `RequestPolicy`: 5 s a page for the rates (`RATES_POLICY` in
  `db/data/blizzard/meta.py`); for the wiki (`db/data/wiki/__init__.py`),
  2 s a Cargo page with six attempts to wait out a rate limit
  (`CARGO_POLICY`), and 0.5 s an article, asked for once
  (`ARTICLE_POLICY`). No third source, no API keys.
- `.venv/bin/python -m door.sentry --once` is not read-only: it renames a
  suspect strategy file to `.md.quarantined`.
- Never `docker compose down -v`: it deletes the database volume.

## Style

- `%`-formatting, never f-strings or `.format()` (ruff's UP031/UP032 are off
  for this).
- Every function and method carries full type annotations, and a record
  that crosses a module boundary is a dataclass, NamedTuple or TypedDict,
  not an ad-hoc dict or tuple. A TypedDict is a shape that is or becomes
  JSON, or holds optional keys; a NamedTuple is a row a parser or a query
  yields, which a reader may unpack; a dataclass is the rest -
  configuration, a mutable tally, or a record that must not act as a tuple
  (keyword-only, or carrying a check or a derived field). `Any` is for
  arbitrary JSON. mypy holds the annotations in CI (`[tool.mypy]` in
  pyproject.toml, `warn_unused_ignores` among them); the tests need none
  and are not checked.
- A type alias is a PEP 695 `type` statement, never a bare assignment; a
  recursive one names itself unquoted. It is defined in one module and
  imported everywhere else; `test_every_type_alias_is_a_type_statement`
  fails a bare one.
- Imports sit in the module's import block; an optional dependency is
  imported there inside `try`/`except ImportError`, as pgserver is in
  `db/psql/__init__.py`. A function-level import is a deliberate deferral
  and says why, `# noqa: PLC0415  # <why>`; ruff fails any other outside
  `tests/`.
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
for p in .venv .cache-blizzard .cache-wiki db/psql/cluster db/raw .claude/worktrees; do .venv/bin/desloppify exclude $p; done
```

The target score is set with `desloppify config set target_strict_score
<n>` and lives only in that local config. A subjective review is blind:
its reviewers score from the code alone, never from a score or a target.

The loop, from the repo root:
`PATH="$PWD/.venv/bin:$PATH" .venv/bin/desloppify scan --path .` (the scan
counts bandit as installed only when PATH finds it; without it Security
confidence stays at 0.6), then `next`, fix, `plan resolve <id> --attest
"I have actually ... not gaming ..."` (`next` prints the exact command),
repeat; `status` shows the scores. Follow the scan's own
instructions. Its commits follow the house style above, not its
`desloppify: ...` template.
