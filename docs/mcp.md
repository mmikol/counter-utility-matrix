# The MCP servers

One set of tools, served over the
[Model Context Protocol](https://modelcontextprotocol.io) by the door
over all three layers (`door/mcp/`): the data layer's pulls, the facts
layer's facts, and the inference layer's solver and playbook. A Claude
Code session calls them as MCP tools; the board, the refresher, Docker's
entrypoint and the shell call the same functions in-process. The door
gates every write: a write to Postgres or the playbook runs under one of
its tools, and the sentry's quarantine rename of a bad strategy file
(`door/sentry.py`) is the one write outside it, so a session and the
board see the same numbers. Reading is direct: the facts and inference
layers and the board `SELECT` over their own connection.

## The two servers

`.mcp.json` at the root registers both for a Claude Code session opened
in the repo:

| server | transport | reaches | started by |
| --- | --- | --- | --- |
| `countrix` | stdio: `.venv/bin/python -m door.mcp` | the local embedded cluster at `db/psql/cluster` (or whatever `DATABASE_URL` names) | the session, on demand |
| `countrix-docker` | Streamable HTTP: `http://localhost:8020/mcp` | the compose stack's PostgreSQL - the database the board at :8017 shows | the `data` container, after it has built the database |

They expose the same tools. The skills prefer `countrix-docker`
when the stack is up, so what a session changes is what the board shows;
the headless agents' run (`orchestrator.py agents`) is allowed an explicit
list of tools on these two servers and no built-in tool at all.

The HTTP door checks who is knocking: it binds to 127.0.0.1, answers only
a request whose `Host` and `Origin` name it - a local name, or `data`, the
name the board's container calls it by - caps a request at one megabyte
and a batch at twenty messages, allows 120 tool calls per client address
per minute, and
requires `Authorization: Bearer <token>` when `COUNTRIX_MCP_TOKEN`
is set (in `.env`; `.mcp.json` sends it from the same variable). Every
tool call is a line in the audit log, `db/raw/audit.jsonl`, that the
sentry reads - over either transport and in-process, where the refresher
and the shell call a tool directly; a line it cannot write is noted on
stderr and the call goes on. The `query` tool connects as
`matrix_reader`, a login that can only `SELECT`, runs one read-only
statement with a timeout, and refuses SQL that reaches for files or
servers. The whole threat model is in [security.md](security.md).

The protocol (`door/mcp/server.py`) and its transports are dependency-free -
a few hundred lines instead of the SDK, so the door has nothing to audit:
JSON-RPC 2.0, one message per line over stdio (`stdio.py`), and the same
surface over HTTP (`http.py`) with a `Mcp-Session-Id`
per client, the Host-and-Origin guard all three servers share
(`db/web.py`), `GET /health` for the containers' healthchecks - the
database's state (`db.psql.schema.state`: empty, stale, unfilled or
current) and its counts, or degraded when it is out of reach - and `405`
on a bare `GET /mcp`. The methods:
`initialize`, `ping`, `tools/list`, `tools/call`, `resources/list`,
`resources/read`, `resources/templates/list`, and an empty
`prompts/list`. It logs to stderr, since stdout is the wire.

A call the caller can fix - an unknown hero, a bad weight, SQL that
Postgres rejects - raises `db.Refusal`: the reply is `isError` with the
reason, and the audit line says refused. Every call, in-process too, is
checked against the tool's schema before the tool runs: an argument it
does not take, one it requires left out, a value of the wrong type or
outside the declared values is refused the same way. A request the wire
cannot serve - params that are not an object, a tool name or uri that is
not a string or names nothing served - is `INVALID_PARAMS` (-32602), and a
message without a string method `INVALID_REQUEST` (-32600). Anything else
is the server's fault, a playbook that does not load included: the reply
is `INTERNAL` (-32603) with the error's type and message, the traceback
goes to stderr, and the audit line says crashed, in the reply's words,
which the sentry counts.

## From a shell

```bash
.venv/bin/python -m door.mcp list                          # the tools
.venv/bin/python -m door.mcp call db_status                # run one, print its text
.venv/bin/python -m door.mcp call infer '{"map": "King'"'"'s Row", "red": ["Zarya"]}'
./docker-db .venv/bin/python -m door.mcp call db_status    # the same, against the stack's database
.venv/bin/python -m door.mcp --http 127.0.0.1:8020         # serve over HTTP yourself
```

Every tool returns text for a person and a JSON payload for a program;
`call` prints the text and exits 0. A refused call, or a name no tool
has, prints `error: <reason>` to stderr and exits 1; arguments that are
not one JSON object print the usage and exit 2.

## Resources

The strategy files are also served as MCP resources, so a session can
read the playbook without a tool call: `strategy://<id>` is one file (its
frontmatter and prose, `text/markdown`), and `strategy://tuning-log` is
the audit trail of every change to them.

## The package - `door/`

`door/` stands over all three layers: it imports `db`, `facts` and
`inference`, and none of them imports it (`tests/test_docs.py` holds the
direction). Beside the MCP server it holds the two daemons that run on a
clock: the refresher, which calls the door's tools, and the sentry, which
watches what the tools cannot.

| file | purpose |
| --- | --- |
| `mcp/` | The MCP server and its tools, below. |
| `refresh.py` | The clock: the daily refresh ([db.md](db.md) has its schedule and settings), and the full one once the wiki cache is a week old. |
| `sentry.py` | The guard. Every thirty seconds: every strategy file must load through the catalog and read like a strategy, or it is quarantined (`.md.quarantined`); instruction-like text in the database's free text is flagged; the door's audit log is tallied. Its report, `db/raw/sentry.json`, is what `orchestrator.py status` prints; `.venv/bin/python -m door.sentry --once` is one pass from a shell. |

### `mcp/` - the server and its tools

The servers and the transports are above, the tool reference below.

| file | purpose |
| --- | --- |
| `server.py` | The protocol: JSON-RPC 2.0 answered from a server's tools and resources, whichever transport carries it - `initialize`, `tools/list`, `tools/call`, `resources/*`, each response a typed record. Dependency-free, like the four modules below, so the door has nothing to audit but its own few hundred lines. |
| `stdio.py` | The stdio transport `.mcp.json` launches: one message a line on stdin, each answer a line on stdout. |
| `http.py` | The Streamable HTTP transport (`POST /mcp`, `GET /health`): the bearer token, the body and batch caps, and the rate limit per client address. |
| `schema.py` | A tool as the protocol serves it: its arguments as JSON Schema (`ToolSchema`, a `Property` per argument), its reply (`ToolReply`: text, and the same as JSON), and the `Tool` that checks every call against the schema before the tool runs. |
| `audit.py` | The audit line every call leaves in `db/raw/audit.jsonl`, through any door, in-process too; the sentry reads it. |
| `registry.py` | The one registry every family declares its tools into (`REGISTRY`, its decorator `tool`). A `ToolSpec` is a tool as registered: name, description, JSON schema, function, its family - the module the function is defined in - and for a pull the source it reads. `Registry` lists the tools family by family in `FAMILIES`' order, whichever family imports first, refuses a name twice and derives the pulls; `run` is the audited in-process call, `write_docs` the tool reference below. `Context` is where a call lands - the database, the page caches, the log - and carries the registry, through which one tool calls another. |
| `tools.py` | Every family imported, so the registry is whole; the `Context` the servers, the refresher and the board use, and `run_tool`, the in-process call. |
| `pulls.py` | `list_sources`, the ten `pull_*` tools in dependency order (one source and domain each, each stated once through `pull_tool`), `load_authored`, `sync_all`. |
| `lifecycle.py` | The database's life: `db_status`, `db_init`, `db_migrate`, `db_rebuild`, `export_csv`, `db_docs`, and read-only `query`, which says when it cut rows. |
| `boards.py` | `BOARD`, the five properties every board tool takes, and `board_tool`, which registers a tool over them and hands its function the one `Draft` they name. |
| `facts.py` | The facts layer through the door: `roster` and the board tool `facts`. |
| `solver.py` | The inference layer through the door: the board tools `infer`, `evaluate` and `board`, and `reach`. |
| `playbook.py` | `metrics`, the vocabulary a strategy may reference, `strategies`, the tools that write the playbook (`tune`, `add_strategy`, `infer_strategy`, `derive_strategies`), each reloading the mirror after the write, and `tuning_log`. The strategies are also served as `strategy://` resources. |
| `__main__.py` | `.venv/bin/python -m door.mcp` serves over stdio (what `.mcp.json` launches); `--http HOST:PORT` serves over HTTP (the `data` container); `list` and `call NAME [JSON]` are the shell. |

## The tools

<!-- generated:tools -->
33 tools, in the order the server lists them. Regenerated by `.venv/bin/python -m door.mcp call db_docs`.

| tool | does | arguments |
| --- | --- | --- |
| `list_sources` | The sources the data layer pulls from, what each supplies, and how many pages its cache holds. | none |
| `pull_heroes` | Blizzard's roster: heroes, roles, subroles, portraits, ability and perk text. Run first - everything links to heroes. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `pull_kits` | The wiki's Cargo ability table and hero articles: weapons and firing configs, every published number, ability kinds and keywords, hero health pools. Run after pull_heroes. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy<br>`supplement` (boolean): also read each hero article for the flags Cargo lacks (default true) |
| `pull_maps` | The wiki's map pool: maps, game modes, playable combinations, and each map's stages: a Control map's three, a Flashpoint map's five points, a Hybrid map's two phases, an Escort map's stretches where its article names them. Push maps have none. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `pull_terrain` | The wiki's map articles: per map, the mentions of each terrain feature (chokes, interiors, high_ground, flanks, sightlines, open_ground, hazards, cover) and the mentions per thousand words; the same per stage, where the article has text about the stage. Reloads map_terrain and stage_terrain whole. Run after pull_maps: a stage must exist before its terrain. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `pull_patches` | The wiki's patch list, so every rates snapshot can say which game version it measured. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `pull_seasons` | The wiki's Season pages: every season that has started, with its start date. Restamps every rates snapshot with its season. Run before pull_rates. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `pull_rates` | Blizzard's win/pick/ban rates as a NEW dated snapshot, by rank tier and by map (Competitive Role Queue - the page offers no Open Queue - console, Americas). Slow when uncached: ~40 pages, 5s apart. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `pull_playstyles` | The wiki's team-composition page: which playstyle (dive, brawl, poke) each hero belongs to. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `pull_synergies` | The Synergy section of every hero's wiki article: one row per pair, score 2 when both articles name each other, 1 when one does, the wiki's advice as the note. Run after pull_heroes. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `pull_counters` | The Match-Up column of every hero's wiki article: each written cell read as a verdict and stored as a directed edge, one row = countered_by answers hero. Reloads the table whole. Run after pull_heroes. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `load_authored` | Store the one input a user writes: the mirror of the strategies in inference/strategies/. A whole-truth reload. | none |
| `sync_all` | Every pull_* tool in dependency order, then the strategies mirror, then the CSV mirror. On a populated database this is an update: entities refresh in place, rates append a snapshot. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `db_status` | Which database the tools are pointed at, its state (empty, stale, unfilled or current - what the containers wait on), its table and row counts, and the rates snapshots it holds. | none |
| `db_init` | Apply the migrations to an EMPTY database (schema only; sync_all fills it). Refuses a database that already has tables. | none |
| `db_migrate` | Apply the migrations the ledger has not recorded, in place: a populated database catching up with the files without a rebuild. Nothing pending is not an error. | none |
| `db_rebuild` | Drop everything, reapply the migrations and run sync_all. | `refresh` (boolean): fetch every page again instead of reading the cache; a page that fails to fetch keeps its cached copy |
| `export_csv` | Refresh db/raw/*.csv: one CSV per table. | none |
| `db_docs` | Regenerate the generated sections of the docs: the ERD and data dictionary in docs/db.md from the live schema, the catalog and vocabulary in docs/inference.md from the strategies files, the tool reference in docs/mcp.md. | none |
| `query` | Run read-only SQL against the database (one SELECT, WITH, EXPLAIN, SHOW, TABLE or VALUES statement, first 200 rows). Every table is documented in the data dictionary in docs/db.md. | `sql` *required* (string): the statement |
| `roster` | Every hero with role, subrole, health pool, portrait and status (released, or announced with its release day - shown, never picked), plus the map pool with modes - the vocabulary the board tools accept. | none |
| `facts` | The FACTS LAYER: every fact the database holds about a board - independent facts per named hero and for the map, joint facts per team once it has picks (shape, effective HP, damage and healing floors, range, tempo, cohesion, coverage...), and matchup facts once both teams have picks. Numbered F1.. for citation. | `map` (string): map name (any spelling)<br>`red` (array): the enemy team's revealed heroes<br>`blue` (array): your team's locked heroes<br>`bans` (array): the match's bans, up to five (each team's two and the lobby's), all optional; neither team can pick them<br>`side` (attack \| defense \| ): blue's side on an Escort or Hybrid map (red gets the other); ignored on Control, Push, Flashpoint<br>`format` (lines \| json): lines (default) or json |
| `infer` | The INFERENCE LAYER: the optimal six for this board under the markdown strategies in inference/strategies/ (players assumed to play optimally). Locked blue picks are kept; the rest is searched. Returns the comp, per-pick reasons with fact citations, the strategy score breakdown, and alternatives. | `map` (string): map name (any spelling)<br>`red` (array): the enemy team's revealed heroes<br>`blue` (array): your team's locked heroes<br>`bans` (array): the match's bans, up to five (each team's two and the lobby's), all optional; neither team can pick them<br>`side` (attack \| defense \| ): blue's side on an Escort or Hybrid map (red gets the other); ignored on Control, Push, Flashpoint<br>`top` (integer): alternatives to return (default 5)<br>`pool` (integer): candidates per role the search keeps (default 6)<br>`compact` (boolean): true: a reply small enough to carry under a playbook of hundreds. The structured payload then has its own keys: map, side, red, blue, score, terms (how many scoring terms the full reply carries), idle, silent (applying, metric not varying on this board) and largest (the 15 heaviest terms, each an id and its weighted value) |
| `evaluate` | Score a FULL blue six against the strategies without searching: the breakdown per strategy, constraint violations, and how it ranks against the optimum. | `map` (string): map name (any spelling)<br>`red` (array): the enemy team's revealed heroes<br>`blue` *required* (array): your team's locked heroes<br>`bans` (array): the match's bans, up to five (each team's two and the lobby's), all optional; neither team can pick them<br>`side` (attack \| defense \| ): blue's side on an Escort or Hybrid map (red gets the other); ignored on Control, Push, Flashpoint |
| `reach` | Can the playbook ever pick this hero? A board that suits it - one of its maps, a red it answers, the match's bans spent on the rivals holding its seat - on which it is in the optimal six; with none, the closest it came. A hero that cannot be reached is one the facts or the strategies cannot see. | `hero` *required* (string): a released hero (any spelling) |
| `board` | The whole board at any stage of the draft (no map, a map, a side, bans, red's picks as they reveal): blue's optimal six as the best counter to red's selection - to their likely six until they reveal a pick (blue's own picks never constrain it), red's best counter to yours, both current comps scored on those scales, your picks against red's best counter, your locked picks with the empty slots filled, the fight odds (each seat's share of its own optimal, and the two against each other), the game plan in prose, the shapes the queue and the playbook's limits allow, and red's likely six from the data alone (a two-two-two from the map's pick rates and the wiki's synergies, past the bans; static for the board, no strategy read). | `map` (string): map name (any spelling)<br>`red` (array): the enemy team's revealed heroes<br>`blue` (array): your team's locked heroes<br>`bans` (array): the match's bans, up to five (each team's two and the lobby's), all optional; neither team can pick them<br>`side` (attack \| defense \| ): blue's side on an Escort or Hybrid map (red gets the other); ignored on Control, Push, Flashpoint<br>`pool` (integer): candidates per role the search keeps (default 6)<br>`weights` (object): {heuristic id: 0..10} - weights to score this board under instead of the files' (the playbook tab's sliders); the files are untouched |
| `metrics` | The vocabulary a strategy may reference: every metric key with its meaning - team.*, enemy.* (the same for the red side), matchup.*, map.*, world.* - and which are text. What /strategy reads to infer a heuristic's metric or a constraint's expression from prose. | none |
| `strategies` | The inference layer's catalog - STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS: every markdown strategy with its kind (constraint, heuristic or assumption), a constraint's form (limit, scored, draft), metric, direction, weight and expressions. | none |
| `tune` | Change one strategy's frontmatter - its weight, a params dial, or a when/require/bonus/penalty expression - validated through the catalog before it is written, mirrored into the database, and logged with the reason in inference/strategies/tuning-log.md. | `id` *required* (string): the strategy's id (its filename)<br>`field` *required* (string): weight \| direction \| soft \| when \| require \| bonus \| penalty \| metric \| params.NAME<br>`value` *required* (any): the new value: a number, a boolean, or an expression<br>`reason` *required* (string): why, in a sentence<br>`by` (string): who asked, for the log line (default claude-code-session; the board says so) |
| `add_strategy` | Store a new strategy in inference/strategies/ from its name, kind and prose plus the frontmatter /strategy inferred - a heuristic's metric/direction/weight, or a constraint's require or when/bonus/penalty and params; an assumption is prose and needs nothing. The prose is three sentences at most. Validated through the catalog before the file exists, mirrored into the database, logged. Left with nothing inferred it lands as a draft the solver ignores. | `id` *required* (string): lowercase-kebab, becomes the filename<br>`name` *required* (string)<br>`kind` *required* (constraint \| heuristic \| assumption)<br>`body` *required* (string): the prose: what it means and why<br>`reason` *required* (string): why it was added, in a sentence<br>`metric` (string): heuristics: a numeric key from `metrics`<br>`direction` (maximize \| minimize)<br>`weight` (number): 0..10; 1-4 is the working range<br>`when` (string): a guard expression; optional<br>`require` (string): constraints: a limit expression<br>`soft` (boolean): with require: charge `penalty` instead of discarding<br>`bonus` (string): constraints: an expression added while `when` holds<br>`penalty` (string): constraints: an expression (or a number with soft) subtracted<br>`params` (object): NAME: number dials the expressions read as params.NAME<br>`category` (string) |
| `infer_strategy` | Complete a draft (or rewrite a strategy's scoring): set several frontmatter fields at once - metric/direction/weight, when/require/bonus/penalty, params - validated as a whole, mirrored, logged as one line. | `id` *required* (string)<br>`reason` *required* (string): how the fields follow from the prose<br>`metric` (string): heuristics: a numeric key from `metrics`<br>`direction` (maximize \| minimize)<br>`weight` (number): 0..10; 1-4 is the working range<br>`when` (string): a guard expression; optional<br>`require` (string): constraints: a limit expression<br>`soft` (boolean): with require: charge `penalty` instead of discarding<br>`bonus` (string): constraints: an expression added while `when` holds<br>`penalty` (string): constraints: an expression (or a number with soft) subtracted<br>`params` (object): NAME: number dials the expressions read as params.NAME<br>`category` (string) |
| `derive_strategies` | Complete every draft (a strategy with only a name, a kind and prose) by asking Claude Code in print mode - the subscription, no key - for the frontmatter, validated through the catalog and logged. Runs where the claude CLI is signed in (the host); elsewhere drafts stay pending. | `ids` (array): which drafts (default: all) |
| `tuning_log` | The audit trail of every change to the strategies' frontmatter, newest last. | `lines` (integer): how many (default 20) |
<!-- /generated:tools -->
