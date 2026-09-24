# The DATA LAYER - `db/`

Pull every source, clean it, store it in Postgres, and serve the tools
that do so. This layer owns `DATA = HEROES ∪ MAPS ∪ META`: the tables a
board's facts are derived from. Every row carries a `source_id`, and that
is the only distinction drawn between what was measured, what was judged
and what was written by hand. Only the strategies are written by hand.

**One door.** The MCP tools in `mcp/` are the only way to drive
the layer, and the only way in for a write. A Claude Code session calls
them over MCP, the `refresher` container calls them in-process, Docker's
entrypoint calls them to build the database, and a shell calls them the
same way. Reads are not gated: the UI and inference layers open their own
connection through `db.psql.default_dsn()`, which is what lets the board
load a World per request:

```bash
.venv/bin/python -m db.mcp list                        # the tools
.venv/bin/python -m db.mcp call db_rebuild             # build from scratch
.venv/bin/python -m db.mcp call sync_all               # update everything
.venv/bin/python -m db.mcp call pull_rates '{"refresh": true}'
```

The root's `orchestrator.py` drives the same tools for the whole stack.

## Layout

```
db/
  __init__.py        where things live, and the scope; the package's map
  refresh.py         the daily refresh (the refresher container's process)
  sentry.py          the guard (the sentry container's process)
  web.py             what the three HTTP servers share, and the MCP client
  mcp/               the MCP server and the tools - the one door
  data/              the sources, page to table
    blizzard/        overwatch.blizzard.com
    wiki/            overwatch.fandom.com
    authored/        the `sources` row of the strategies mirror
    fetch.py         the page cache, its freshness policy and the request loop
    names.py         matching hero, map and ability names across sources
  psql/              the database: where it is, the schema, the ledger
    migrations/      the schema as a sequence
    cluster/         the embedded Postgres a local build creates (gitignored)
  raw/               one CSV per table, the mirror (exported, gitignored)
```

### What the layer shares

| file | purpose |
| --- | --- |
| `__init__.py` | What the whole layer agrees on, declared once: where the repo, the caches and the mirror live, the shape of a `sources` row (`Source`: code, name, url), the ability kinds and perk tiers the migrations seed, and the scope every rates snapshot is pinned to - console, controller, Americas. `Refusal` is the one error a caller can fix - an unknown name, a bad value, a board that cannot stand - which every layer raises and every door answers as the caller's; anything else is the server's fault. `embed` rewrites one generated section of a markdown file, for every layer that generates docs. |
| `data/__init__.py` | `PullSummary`, what every source's `run()` returns: the tables it wrote, beside its own counts. `ArticlePullSummary` adds `missing`, the articles or pages that would not fetch, for a pull that reads one per entity. |
| `data/fetch.py` | `cached_get`: one page, from the cache if it is there and fresh. `cached`: the cache sequence every source reads through - the fresh copy, else a new one written, else the stale copy. `request`: one page under a `RequestPolicy` - its attempts, backoff, timeout and the pause after a page - retried while attempts remain. `max_age`: the freshness policy for a block - a build keeps every cached page, a refresh refetches them, and a page that fails to refetch keeps its cached copy. `session`: a requests session that says who we are. `PullContext`: what a pull's `run()` takes beside its connection - the page cache, the session and the log, stderr unless the caller names another, since over stdio stdout is the MCP wire. `prepare_cache`: the cache directory a tool hands a pull. |
| `data/names.py` | `name_key` recognises the same hero or map across sites ("Lúcio", "Lucio"; "D.Va", "DVa") by folding accents and punctuation. `ability_key` recognises the same ability across Blizzard and the wiki by dropping one trailing parenthetical. |
| `sentry.py` | The guard. Every thirty seconds: every strategy file must load through the catalog and read like a strategy, or it is quarantined (`.md.quarantined`); instruction-like text in the database's free text is flagged; the door's audit log is tallied. Its report, `raw/sentry.json`, is what `orchestrator.py status` prints; `python -m db.sentry --once` is one pass from a shell. |
| `refresh.py` | The clock: the daily refresh below, and the full one once the wiki cache is a week old. |
| `web.py` | What the three HTTP servers - the MCP door, the inference service and the board - share. `LocalServer` answers to the local names (`LOCAL_HOSTS`) and any host it is started with (`--allow-host`); `Handler` checks every request's `Host` and `Origin` against them before any route runs (`request_allowed`) and answers 403 otherwise, so a page rebound to the address by DNS is refused on every method, reads included. It sends JSON and static bytes, and logs one line on stderr for a request that failed and for each of its `timed` routes, the solves, with the seconds it took. `failure` is the reply to a request that raised: a `Refusal` is 400 with its message; anything else is 500 with the error's type and message, and its traceback goes to stderr, never to the caller. The MCP door draws the same line in JSON-RPC's words. `call_tool` is one `tools/call` over the door's HTTP transport, read into a `CallReply` - the text, the structured payload and whether it is an error: the tool's refusal, the door turning the call away, or no server answering - for the board's one write and `orchestrator.py`. Stdlib only, besides `Refusal`, so the MCP server that stands on it stays dependency-free. |

### `data/` - one package per source

Each source package owns the whole path from page to table. Its
`__init__.py` names the endpoints, the `sources` row its pages become and
what its modules share: for the wiki, the client that talks to the
MediaWiki endpoint and `fetch_articles`, through which every pull that reads
one article per hero or map records an article that will not fetch and
reads the rest; for Blizzard, `attr`, a tag's attribute as text. Each
domain module is one `run(connection, pull)` the tools call, `pull` a
`PullContext` holding the page cache, the session and the log: fetch
(cached), extract the values from the markup, normalise them, store them,
and return a `PullSummary`.

| package | module | stores |
| --- | --- | --- |
| `blizzard/` | `heroes.py` | the roster: heroes, roles, subroles, portraits and icons, ability and perk text. Runs first; everything links to heroes. Blizzard publishes prose and no numbers. A hero page that will not fetch is listed under `missing`, and that hero keeps the text it had. |
| | `meta.py` | win, pick and ban rates as a dated snapshot, sliced by skill tier and by map. Competitive Role Queue (the page offers no Open Queue), console, Americas - all recorded on the snapshot. |
| `wiki/` | `heroes.py` | hero kits from the Cargo Abilities table: weapons and their firing configs, abilities, perks, keywords, and every stat as a measurement, through the three modules below. Also the announced heroes: a Cargo hero the roster lacks whose article is marked upcoming gets a row (role, subrole, health, release day, status `announced`) so its kit loads ahead of release; Blizzard listing it later flips the status to released. Runs after `blizzard.heroes`. |
| | `kit_rows.py` | a Cargo Abilities row read into one hero's kit: a weapon's firing mode, an ability or a perk, each a TypedDict holding the keys its kind guarantees; weapons sorted by firing slot. |
| | `hero_articles.py` | a hero's article: the interaction flags and other stats Cargo does not register, merged into the kit where Cargo left them empty; the health pool from the infobox; the announcement of a hero marked upcoming. |
| | `kit_store.py` | the kits into the tables: weapons, firing configs, stats, modifiers and perk links reloaded whole, abilities classified and the ones Blizzard omits added, each hero's pools set; a tally of every row written. |
| | `maps.py` | maps, game modes and stages from the Maps article's Standard Play section. |
| | `terrain.py` | the ground each map's article describes: the sections about play kept, the lore dropped, and the mentions of each terrain feature - chokes, interiors, high ground, flanks, sightlines, open ground, hazards, cover - counted per map and per thousand words (`map_terrain`), and the same per stage over the text the article has about that stage (`stage_terrain`). Reloads both tables. Runs after `wiki.maps`: a stage must exist before its terrain. |
| | `patches.py` | game versions from the Patches cargo table; snapshots link to the patch current at capture. Runs before the rates pulls. |
| | `seasons.py` | every season that has started, with its start date, from the Season article's subpages; note is the subpage. Reloads the table and restamps every rates snapshot with its season. Runs before the rates pulls. |
| | `playstyles.py` | the team-composition playstyles (dive, brawl, poke) and the heroes listed under each. |
| | `synergies.py` | which heroes work with which, from the Team Synergy cells in the "Match-Ups and Team Synergy" section of every released hero's article: a pair is stored once, score 2 when both articles claim it, 1 when one does; note is the wiki's advice cut to one clause. Reloads the table. Runs after `blizzard.heroes`. |
| | `matchups.py` | who answers whom, from the Match-Up cells of the same section, through `synergies.py`'s section and row parsing. Each written cell is a verdict from the article hero's seat: the other hero answers this one, this one answers the other, or neither. The wiki's MATCHUP or VS. rating decides where there is one; otherwise the prose is scored. A verdict either way is one directed edge in `counters`; a pair the two articles contradict on gets none. Reloads the table. Runs after `blizzard.heroes`. |
| | `markup.py` | reading the wiki's two markups - Cargo's rendered HTML and article wikitext - and the tidying both need; the link pattern; a section's body, cut at the next heading of any depth. |
| | `measurements.py` | a stat value ("75 over 0.59 seconds", "10 - 20 meters", a yes/no glyph) into value, unit, window and condition. |
| | `weapons.py` | the wiki's one-entry-per-firing-mode list grouped into weapons and their configs. |
| | `modifiers.py` | what a buff scales and who it lands on, recovered from the value's wording and the ability's keywords. |

### `mcp/` - the door

The servers, the transport and the full tool reference are in
[mcp.md](mcp.md).

| file | purpose |
| --- | --- |
| `server.py` | The protocol: JSON-RPC 2.0 answered from a server's tools and resources, whichever transport carries it - `initialize`, `tools/list`, `tools/call`, `resources/*`, each response a typed record. Dependency-free, like the four modules below, so the door has nothing to audit but its own few hundred lines. |
| `stdio.py` | The stdio transport `.mcp.json` launches: one message a line on stdin, each answer a line on stdout. |
| `http.py` | The Streamable HTTP transport (`POST /mcp`, `GET /health`): the bearer token, the body and batch caps, and the rate limit per client address. |
| `schema.py` | A tool as the protocol serves it: its arguments as JSON Schema (`ToolSchema`, a `Property` per argument), its reply (`ToolReply`: text, and the same as JSON), and the `Tool` that checks every call against the schema before the tool runs. |
| `audit.py` | The audit line every call leaves in `db/raw/audit.jsonl`, through any door, in-process too; the sentry reads it. |
| `registry.py` | The one registry every family declares its tools into (`REGISTRY`, its decorator `tool`). A `ToolSpec` is a tool as registered: name, description, JSON schema, function, its family - the module the function is defined in - and for a pull the source it reads. `Registry` lists the tools family by family in `FAMILIES`' order, whichever family imports first, refuses a name twice and derives the pulls; `run` is the audited in-process call, `write_docs` the tool reference in [mcp.md](mcp.md). `Context` is where a call lands - the database, the page caches, the log - and carries the registry, through which one tool calls another. |
| `tools.py` | Every family imported, so the registry is whole; the `Context` the servers, the refresher and the board use, and `run_tool`, the in-process call. |
| `pulls.py` | `list_sources`, the ten `pull_*` tools in dependency order (one source and domain each, each stated once through `pull_tool`), `load_authored`, `sync_all`. |
| `lifecycle.py` | The database's life: `db_status`, `db_init`, `db_migrate`, `db_rebuild`, `export_csv`, `db_docs`, and read-only `query`, which says when it cut rows. |
| `boards.py` | `BOARD`, the five properties every board tool takes, and `board_tool`, which registers a tool over them and hands its function the one `Draft` they name. |
| `facts.py` | The UI layer through the door: `roster` and the board tool `facts`. |
| `solver.py` | The inference layer through the door: the board tools `infer`, `evaluate` and `board`, and `reach`. |
| `playbook.py` | `metrics`, the vocabulary a strategy may reference, `strategies`, the tools that write the playbook (`tune`, `add_strategy`, `infer_strategy`, `derive_strategies`), each reloading the mirror after the write, and `tuning_log`. The strategies are also served as `strategy://` resources. |
| `__main__.py` | `python -m db.mcp` serves over stdio (what `.mcp.json` launches); `--http HOST:PORT` serves over HTTP (the `data` container); `list` and `call NAME [JSON]` are the shell. |

### `psql/` - the database

| file | purpose |
| --- | --- |
| `__init__.py` | Where the database is (`DATABASE_URL`, or the embedded cluster at `db/psql/cluster`; a host without pgserver must set `DATABASE_URL`); how a source registers the `sources` row its rows carry; how names look up ids; what a capture is stamped with (now, the current patch and season); the CSV export and its `EXPORT.json` mark naming the database it came from. Knows no particular source or table. |
| `schema.py` | Applies migrations and records them in the `schema_migrations` ledger; `pending` says which files the database has not seen; `state` says how ready the database is - empty, stale, unfilled or current - for every reader of readiness, and `python -m db.psql.schema` prints it for the container entrypoint; `rebuild` drops everything and reapplies; `generate_docs` writes the ER diagrams and the data dictionary at the end of this document from the live schema, each table described by the `--` block directly above its `CREATE TABLE` (`table_prose`) or a later `COMMENT ON TABLE`. |
| `migrations/` | The schema as a sequence, one file per step: `001` sources and the foundation, `002` heroes, `003` maps, `004` meta, `005` playbook, `006` inference, `007` the three layers, `008` the ledger, `009` and `014` the tables that recorded matches, added and dropped again, `010` constraints and heuristics (the `strategies` table), `011` and `012` the `matrix_reader` login the `query` tool connects as, with the dynamic-SQL functions withdrawn from `PUBLIC`, `013` the assumption kind, `015` announced heroes, `016` the playbook each `strategies` row was mirrored from, `017` that column's comment, `018` `map_playstyle` and `comp_archetypes` dropped, `seasons` and `synergies` pulled from the wiki, `019` `map_strategy` and the third source's rates, snapshots and `sources` row dropped, `counters` pulled from the wiki, `020` `map_terrain`, the terrain features each map's wiki article names, `021` `stage_terrain`, with every Hybrid map's two phases and an Escort map's named stretches stored as stages, `022` the `strategies.playbook` comment under the Countrix name. A statement in an applied migration is never edited; a change is a new file, and a populated database catches up with `db_migrate`. The `--` prose is documentation - the data dictionary reads the block above each `CREATE TABLE` - and is kept current. |
| `cluster/` | The embedded Postgres cluster `pgserver` creates on first touch (gitignored). The compose stack uses its own `postgres` container instead, reachable from the host through `./docker-db`. |

### `data/authored/` - the one input a user writes

The playbook in [`inference/strategies/`](../inference/strategies/) is the
only input written by hand; every other table is filled by a pull tool.
This folder's `__init__.py` declares the `sources` row (`user`) the
`strategies` mirror carries. `load_authored` reloads the mirror from the
files, whole-truth, deriving pending drafts first where the `claude` CLI
is present.

A note that should shape a comp is an assumption in the playbook, where it
is shown on the board, read by the `/comp` session, and tuned and logged
with the rest.

### `raw/` - the mirror

One CSV per table, exported by `export_csv` after every sync, plus
`EXPORT.json` naming the database that exported it. Gitignored. The
parity tests read it, and skip themselves when the mirror came from the
other database.

## The order of a build

`sync_all` runs the pulls in dependency order - `blizzard.heroes`,
`wiki.heroes`, `wiki.maps`, `wiki.terrain`, `wiki.patches`, `wiki.seasons`,
`blizzard.meta`, `wiki.playstyles`, `wiki.synergies`, `wiki.matchups` -
then `load_authored`, then `export_csv`. Entity tables refresh in place;
each rates pull appends a dated snapshot, the series the trend facts
difference. The page caches (`.cache-blizzard/`, `.cache-wiki/` at the
repo root) make every build after the first cost almost no requests.

```mermaid
stateDiagram-v2
    [*] --> Empty: docker compose up<br/>(or pgserver first touch)
    Empty --> Schema: db_init<br/>every migration, no data
    Schema --> Populated: sync_all<br/>every pull tool + load_authored
    Empty --> Populated: db_rebuild<br/>(the entrypoint's move<br/>on an empty database)
    Populated --> Populated: pull_seasons + pull_rates daily,<br/>sync_all weekly (the refresher)<br/>entities upsert in place,<br/>rates APPEND a dated snapshot
    Populated --> Empty: db_rebuild<br/>drop everything
```

Docker's `data` container asks `python -m db.psql.schema` for the
database's state (`schema.state`: empty, stale, unfilled or current), runs
`db_rebuild` on anything but current, then serves the door. `db_status` and
the door's `/health` report the same state, which the other containers
wait on.

## Keeping it fresh

The `refresher` container refreshes the database once a day, so the board
is ready when a game starts. The daily refresh refetches what moves day to
day - the wiki's seasons and the rates (a new dated snapshot) - then
re-mirrors the strategies and re-exports `raw/`.
Once the wiki cache is older than `COUNTRIX_REFRESH_FULL_DAYS` it
runs `sync_all` with refresh on: every page of every source, hero pages
and articles (kits, synergies, counters) included. It also refreshes on start when the cached pages
are older than `COUNTRIX_REFRESH_MAX_AGE_HOURS`. A page that fails
to fetch keeps its cached copy, so a flaky source degrades to yesterday's
numbers rather than an empty table; the board's header shows the capture
date and warns when patches shipped since.

| setting | default | meaning |
| --- | --- | --- |
| `COUNTRIX_REFRESH_AT` | `05:00` | daily time, in the container's `TZ` (UTC unless set) |
| `COUNTRIX_REFRESH_MAX_AGE_HOURS` | `20` | refresh on start when the cache is older than this |
| `COUNTRIX_REFRESH_FULL_DAYS` | `7` | refetch every source (not just the daily set) when the wiki cache is older than this |

Set them in the environment or a `.env` file next to `compose.yaml`; the
loop reads them once, when it starts. The same refresh from a shell,
against whichever database `DATABASE_URL` names:

```bash
.venv/bin/python -m db.refresh --now        # once, now (the daily set; --full for every source)
.venv/bin/python -m db.refresh              # the daily loop
.venv/bin/python -m db.mcp call sync_all '{"refresh": true}'
```

## Widening the meta's granularity

This concerns the *fact* tables - the ones holding rates and playbook
rows. Hero kits, weapons, maps and modes have no such dimensions: a
cooldown is a cooldown in every region, on every platform, at every rank.

**A rebuild drops the database and reapplies the migrations from
scratch,** and the Docker entrypoint does the same the moment the image
carries a migration the ledger lacks. Adding a dimension is never a data
migration - there is no data to migrate. Every dimension below already
has its column, so widening one is an edit to `pull_rates` and a
refetch; a dimension without one is a new migration that adds it, never
an edit to `psql/migrations/004_meta.sql`, which the ledger has already
applied. The schema is not the constraint; the request count is, and it
is multiplicative.

| dimension | column exists? | populated today | to widen it |
| --- | --- | --- | --- |
| tier - `hero_meta` | yes | 9 ranks | already there |
| tier - `map_meta` | yes | all-ranks only | restore the inner loop; ×9 requests |
| region - `hero_meta` | yes | Americas | drop the region pin; ×3 requests |
| region - `map_meta` | yes | Americas | drop the region pin; ×3 requests |
| platform | as `meta_snapshots.platform` | Console | fetch `input=PC` too; ×2 requests |
| input device | yes | controller (entailed by console) | a source that splits PC by device (see below) |
| map stage | `map_stages` 36 rows | stage list loaded | a source with per-stage rates (see below) |
| any - PLAYBOOK tables | deliberately none | - | judgements are tier- and region-agnostic by design: a current read of the game, not a measurement of a population. Dimensioned numbers live in META |

Every dimension has a column; what is missing is data to put in one.
The columns carry the value that used to be implicit: `map_meta.region_id`
says Americas, the playbook tables say all-ranks, `meta_snapshots.input`
says controller. Two are not merely unfetched:

**Input device is not the same as platform**, and only one of them is
published. Blizzard's filter offers `PC` and `Console` - a platform. It
says nothing about whether that player held a controller or a mouse, and
both platforms support both. `meta_snapshots.input` therefore carries the
one value the pin entails - `controller`, because the project pins
console - and a real split would need a source that separates the two;
neither source does.

**Map stages exist; per-stage rates do not.** The stage list is loaded -
36 stages across the ten Control and Flashpoint maps, read from each map's
wiki article - so `map_stages` is populated and `map_meta.stage_id` has a
real vocabulary to point at. No source reports rates *per stage*:
Blizzard's map filter stops at whole maps, so every `map_meta` row keeps
`stage_id` NULL. NULL means the whole map, so `map_meta` uses
`UNIQUE NULLS NOT DISTINCT`; Postgres treats NULLs as distinct by default,
which would let the same hero, map and rank be inserted over and over.

**The request count is the real ceiling.** The dimensions compose
multiplicatively, and the source refuses long sweeps. `map_meta` at full
granularity:

```
30 maps × 9 ranks × 3 regions × 2 platforms = 1,620 requests
```

The rates endpoint began answering `504 Gateway Time-out` partway through
a **280**-request sweep, and then closed connections outright. 1,620 is
not reachable in one pass at any polite rate. What makes it tractable is
that the page cache is permanent and keyed by the full query, so
granularity can be widened one dimension at a time across many runs, each
resuming from what is already on disk. Widen first along whichever
dimension separates the numbers most; rank is the evidence-backed answer:
Widowmaker swings about fifteen points between Bronze and Grandmaster on
a single map, which the all-ranks figure averages away.

Safe to assume: adding a dimension never invalidates existing rows,
because none survive a run; every fact table already carries
`snapshot_id`, so a dimension that belongs to the whole capture (platform,
queue) can be added to `meta_snapshots` without touching the fact tables;
`map_meta` rows already carry `tier_id`, set to the all-ranks tier, so
restoring rank granularity there needs no migration.

## The schema

Generated from the live database by `python -m db.mcp call db_docs`; the
two sections between the markers are rewritten in place, the rest of this
document is written by hand.

### Entity relationship diagrams

<!-- generated:erd -->
Five domains. Three hold the data the sources are pulled for: which
hero (HEROES), on which map (MAPS), performing how well (META).
Every domain
yields independent facts (a selection's own row) and dependent ones
(the selection joined with others: map_meta is heroes ⋈ maps ⋈ meta,
counters and synergies are heroes ⋈ heroes), and a join belongs to
every domain it touches. The other two are the
playbook's record: the judgements pulled from the wiki
(PLAYBOOK) and the mirror of the strategies, the one input a user writes,
that the inference layer solves with (INFERENCE). The composition is
the argmax of the strategies - the constraints, heuristics and assumptions
in inference/strategies/ - over the facts.

```
DATA        = HEROES ∪ MAPS ∪ META
FACTS(D)    = INDEPENDENT(D) ∪ DEPENDENT(D)   for each domain D: its rows; its joins
FACTS       = FACTS(HEROES) ∪ FACTS(MAPS) ∪ FACTS(META)
STRATEGIES  = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS
COMP        = ARGMAX[ STRATEGIES( FACTS ) ]
```

Every table but `sources` and `schema_migrations` also carries
`source_id` → `sources` and a `cao` timestamp. Those edges are left off -
they would connect `sources` to 33 tables and obscure everything else.

#### HEROES

```mermaid
erDiagram
    abilities ||--o{ ability_modifiers : "ability_id"
    abilities ||--o{ ability_stats : "ability_id"
    abilities ||--o{ perk_ability_effects : "ability_id"
    ability_kinds ||--o{ abilities : "kind_id"
    heroes ||--o{ abilities : "hero_id"
    heroes ||--o{ perks : "hero_id"
    heroes ||--o{ weapons : "hero_id"
    perk_tiers ||--o{ perks : "tier_id"
    perks ||--o{ perk_ability_effects : "perk_id"
    perks ||--o{ perk_stats : "perk_id"
    roles ||--o{ heroes : "role_id"
    roles ||--o{ subroles : "role_id"
    stat_keys ||--o{ ability_modifiers : "stat_key_id"
    stat_keys ||--o{ ability_stats : "stat_key_id"
    stat_keys ||--o{ perk_stats : "stat_key_id"
    stat_keys ||--o{ weapon_stats : "stat_key_id"
    subroles ||--o{ heroes : "role_id"
    subroles ||--o{ heroes : "subrole_id"
    weapon_config_slots ||--o{ weapon_configs : "slot_id"
    weapon_configs ||--o{ weapon_stats : "config_id"
    weapons ||--o{ weapon_configs : "weapon_id"
```

#### MAPS

```mermaid
erDiagram
    game_modes ||--o{ map_modes : "mode_id"
    map_stages ||--o{ stage_terrain : "stage_id"
    maps ||--o{ map_modes : "map_id"
    maps ||--o{ map_stages : "map_id"
    maps ||--o{ map_terrain : "map_id"
```

#### META

```mermaid
erDiagram
    competitive_tiers ||--o{ hero_meta : "tier_id"
    competitive_tiers ||--o{ map_meta : "tier_id"
    heroes ||--o{ hero_meta : "hero_id"
    heroes ||--o{ map_meta : "hero_id"
    map_stages ||--o{ map_meta : "stage_id"
    maps ||--o{ map_meta : "map_id"
    meta_snapshots ||--o{ hero_meta : "snapshot_id"
    meta_snapshots ||--o{ map_meta : "snapshot_id"
    patches ||--o{ meta_snapshots : "patch_id"
    regions ||--o{ hero_meta : "region_id"
    regions ||--o{ map_meta : "region_id"
    seasons ||--o{ meta_snapshots : "season_id"
```

#### PLAYBOOK

```mermaid
erDiagram
    heroes ||--o{ counters : "countered_by_id"
    heroes ||--o{ counters : "hero_id"
    heroes ||--o{ playstyle : "hero_id"
    heroes ||--o{ synergies : "hero_id"
    heroes ||--o{ synergies : "other_id"
```

#### INFERENCE

```mermaid
erDiagram
```

#### The whole database

```mermaid
erDiagram
    abilities ||--o{ ability_modifiers : "ability_id"
    abilities ||--o{ ability_stats : "ability_id"
    abilities ||--o{ perk_ability_effects : "ability_id"
    ability_kinds ||--o{ abilities : "kind_id"
    competitive_tiers ||--o{ hero_meta : "tier_id"
    competitive_tiers ||--o{ map_meta : "tier_id"
    game_modes ||--o{ map_modes : "mode_id"
    heroes ||--o{ abilities : "hero_id"
    heroes ||--o{ counters : "countered_by_id"
    heroes ||--o{ counters : "hero_id"
    heroes ||--o{ hero_meta : "hero_id"
    heroes ||--o{ map_meta : "hero_id"
    heroes ||--o{ perks : "hero_id"
    heroes ||--o{ playstyle : "hero_id"
    heroes ||--o{ synergies : "hero_id"
    heroes ||--o{ synergies : "other_id"
    heroes ||--o{ weapons : "hero_id"
    map_stages ||--o{ map_meta : "stage_id"
    map_stages ||--o{ stage_terrain : "stage_id"
    maps ||--o{ map_meta : "map_id"
    maps ||--o{ map_modes : "map_id"
    maps ||--o{ map_stages : "map_id"
    maps ||--o{ map_terrain : "map_id"
    meta_snapshots ||--o{ hero_meta : "snapshot_id"
    meta_snapshots ||--o{ map_meta : "snapshot_id"
    patches ||--o{ meta_snapshots : "patch_id"
    perk_tiers ||--o{ perks : "tier_id"
    perks ||--o{ perk_ability_effects : "perk_id"
    perks ||--o{ perk_stats : "perk_id"
    regions ||--o{ hero_meta : "region_id"
    regions ||--o{ map_meta : "region_id"
    roles ||--o{ heroes : "role_id"
    roles ||--o{ subroles : "role_id"
    seasons ||--o{ meta_snapshots : "season_id"
    stat_keys ||--o{ ability_modifiers : "stat_key_id"
    stat_keys ||--o{ ability_stats : "stat_key_id"
    stat_keys ||--o{ perk_stats : "stat_key_id"
    stat_keys ||--o{ weapon_stats : "stat_key_id"
    subroles ||--o{ heroes : "role_id"
    subroles ||--o{ heroes : "subrole_id"
    weapon_config_slots ||--o{ weapon_configs : "slot_id"
    weapon_configs ||--o{ weapon_stats : "config_id"
    weapons ||--o{ weapon_configs : "weapon_id"
```
<!-- /generated:erd -->

### Data dictionary

<!-- generated:dictionary -->
Generated from the live schema (`python -m db.mcp call db_docs`).

Two columns are omitted from the lists below: `source_id` (which source the
row came from, see `sources`) and `cao` — "current as of", when that row
was read. Every table but `sources` and `schema_migrations` carries both;
`sources` carries `cao` alone and `schema_migrations` neither.

| domain | tables |
| --- | --- |
| **foundation** | `schema_migrations` · `sources` |
| **HEROES** | `abilities` · `ability_kinds` · `ability_modifiers` · `ability_stats` · `heroes` · `perk_ability_effects` · `perk_stats` · `perk_tiers` · `perks` · `roles` · `stat_keys` · `subroles` · `weapon_config_slots` · `weapon_configs` · `weapon_stats` · `weapons` |
| **MAPS** | `game_modes` · `map_modes` · `map_stages` · `map_terrain` · `maps` · `stage_terrain` |
| **META** | `competitive_tiers` · `hero_meta` · `map_meta` · `meta_snapshots` · `patches` · `regions` · `seasons` |
| **PLAYBOOK** | `counters` · `playstyle` · `synergies` |
| **INFERENCE** | `strategies` |


#### `abilities`

*HEROES · `002_heroes.sql`*

kind_id is NULL until pull_kits sets it. Blizzard's markup labels neither weapons nor ultimates, and its ordering does not identify them either, so nothing is guessed at scrape time.

| column | type | null | references |
| --- | --- | --- | --- |
| `ability_id` | integer | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `kind_id` | smallint | yes | `ability_kinds.kind_id` |
| `name` | text | no |  |
| `description` | text | no |  |
| `position` | smallint | no |  |
| `keywords` | text | yes |  |

#### `ability_kinds`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `kind_id` | smallint | no |  |
| `code` | text | no |  |

#### `ability_modifiers`

*HEROES · `002_heroes.sql`*

affects names the quantity scaled, so a query can find every effect on outgoing damage without knowing which stat it was published under. damage_dealt · damage_taken · healing_received · healing_dealt · movement_speed magnitude is a signed percentage: +50 amplifies, -45 reduces.

| column | type | null | references |
| --- | --- | --- | --- |
| `modifier_id` | integer | no |  |
| `ability_id` | integer | no | `abilities.ability_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `affects` | text | no |  |
| `applies_to` | text | yes |  |
| `magnitude` | numeric | no |  |
| `unit` | text | no |  |

#### `ability_stats`

*HEROES · `002_heroes.sql`*

One row per measurement, not per stat. A wiki value like "0.67 shots/s (max charge); 3.33 shots/s (min charge)" becomes two rows sharing a stat_key, separated by `condition`. Units are split into the unit on top and the unit underneath, so nothing has to parse a "/" to know what a number means. denominator_value carries the magnitude underneath - 1 for a plain rate, or the window a burst spans: "125 m/s"              -> 125,  meters  / seconds,  denominator_value 1 "1.25 shots/s"         -> 1.25, shots   / seconds,  denominator_value 1 "75 over 0.59 seconds" -> 75,   hp      / seconds,  denominator_value 0.59 "14 seconds"           -> 14,   seconds / NULL A rate is therefore always value / denominator_value per unit_denominator. value is NULL where the measurement is not numeric (shot types, "partial"). value_text and raw_value always keep the source strings, so anything the parser misreads stays recoverable.

| column | type | null | references |
| --- | --- | --- | --- |
| `ability_stat_id` | integer | no |  |
| `ability_id` | integer | no | `abilities.ability_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `value` | numeric | yes |  |
| `unit_numerator` | text | yes |  |
| `unit_denominator` | text | yes |  |
| `denominator_value` | numeric | yes |  |
| `condition` | text | yes |  |
| `value_text` | text | no |  |
| `raw_value` | text | no |  |

#### `competitive_tiers`

*META · `004_meta.sql`*

'all' is a real member of the tier dimension: it is the unfiltered figure the page reports, and keeping it as a row avoids a nullable dimension key. Region has no such member. Everything here is the Americas, so an "all regions" row would be a second population mixed in beside it. Bronze through Champion, plus the "All Tiers" aggregate the source reports alongside them. rank_order follows the source's own ordering.

| column | type | null | references |
| --- | --- | --- | --- |
| `tier_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |
| `rank_order` | smallint | no |  |

#### `counters`

*PLAYBOOK · `005_playbook.sql`*

Who answers whom: one row means countered_by_id answers hero_id. Pulled from the Match-Up column of every hero's wiki article (pull_counters): each written cell is read from the article hero's seat as a verdict - the other hero answers this one, this one answers the other, or neither - and a verdict either way becomes one directed edge. A pair the two articles contradict on gets no edge. Reloaded whole.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `countered_by_id` | integer | no | `heroes.hero_id` |

#### `game_modes`

*MAPS · `003_maps.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `mode_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |

#### `hero_meta`

*META · `004_meta.sql`*

Rates by region and tier. All rates are percentages as published (47.9 means 47.9%). These rows are across all maps.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_meta_id` | integer | no |  |
| `snapshot_id` | integer | no | `meta_snapshots.snapshot_id` |
| `hero_id` | integer | no | `heroes.hero_id` |
| `region_id` | integer | no | `regions.region_id` |
| `tier_id` | integer | no | `competitive_tiers.tier_id` |
| `win_rate` | numeric | yes |  |
| `pick_rate` | numeric | yes |  |
| `ban_rate` | numeric | yes |  |

#### `heroes`

*HEROES · `002_heroes.sql`*

The composite foreign key makes it impossible to pair a hero with a subrole belonging to a different role than the hero's own. health, shield and armor are the hero's own pool, all in hp. Blizzard publishes none of them, so pull_kits fills them in; a hero with no shield or armor leaves those NULL rather than storing a zero the source never states.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no |  |
| `slug` | text | no |  |
| `name` | text | no |  |
| `role_id` | integer | no | `roles.role_id` |
| `subrole_id` | integer | no | `subroles.subrole_id` |
| `health` | smallint | yes |  |
| `shield` | smallint | yes |  |
| `armor` | smallint | yes |  |
| `portrait_url` | text | yes |  |
| `status` | text | no |  |
| `release_date` | date | yes |  |

#### `map_meta`

*META · `004_meta.sql`*

Rates per map. The source's filters compose, so a hero's rates on King's Row in Bronze are a different figure from its rates on King's Row overall, and both are published; only the whole-map figure is pulled, under tier_id 'all', which keeps the dimension key non-nullable. Region is carried but not swept: every row is the Americas. Widening either is a loop, not a migration - map x tier alone is about 270 requests against a source that refuses long sweeps.

| column | type | null | references |
| --- | --- | --- | --- |
| `map_meta_id` | integer | no |  |
| `snapshot_id` | integer | no | `meta_snapshots.snapshot_id` |
| `hero_id` | integer | no | `heroes.hero_id` |
| `map_id` | integer | no | `maps.map_id` |
| `tier_id` | integer | no | `competitive_tiers.tier_id` |
| `region_id` | integer | no | `regions.region_id` |
| `stage_id` | integer | yes | `map_stages.stage_id` |
| `win_rate` | numeric | yes |  |
| `pick_rate` | numeric | yes |  |
| `ban_rate` | numeric | yes |  |

#### `map_modes`

*MAPS · `003_maps.sql`*

One row per playable combination: this table is the set of matches that can actually be drawn in Open Queue Competitive. Every map currently belongs to exactly one mode, so today this holds one row per map. It is modelled many-to-many anyway because that is what the domain allows - a map can be re-released under a second mode - and because a degenerate join here costs nothing.

| column | type | null | references |
| --- | --- | --- | --- |
| `map_id` | integer | no | `maps.map_id` |
| `mode_id` | integer | no | `game_modes.mode_id` |

#### `map_stages`

*MAPS · `003_maps.sql`*

Stages within a map, in play order (pull_maps). Control maps: the three stages of the Gameplay section's list (Ilios: Lighthouse, Well, Ruins). Flashpoint maps: the five points of the same list. Hybrid maps: the two phases the wiki's Hybrid article names, Assault (the capture point) then Escort (the payload). Escort maps: the stretches of the route, only where the map's article names them - the Gameplay subsections its opening lists (Havana: City Streets, Distillery, Sea Fort). Push maps: none. No source publishes per-stage rates, so map_meta.stage_id stays NULL.

| column | type | null | references |
| --- | --- | --- | --- |
| `stage_id` | integer | no |  |
| `map_id` | integer | no | `maps.map_id` |
| `position` | smallint | no |  |
| `name` | text | no |  |

#### `map_terrain`

*MAPS · `020_map_terrain.sql`*

A map's terrain, counted in its wiki article (pull_terrain). The sections about the ground and how it is played are kept - gameplay, strategy, the per-stage subsections, a rework's changes, the infobox's terrain line - and the lore, place-name lists and media are dropped. Each feature has one pattern (db/data/wiki/terrain.py): chokes, interiors, high_ground, flanks, sightlines, open_ground, hazards, cover. A map whose article has text holds all eight rows, zeros included; a map whose article has under 60 words of kept text holds none. Reloaded whole.

| column | type | null | references |
| --- | --- | --- | --- |
| `map_id` | integer | no | `maps.map_id` |
| `feature` | text | no |  |
| `mentions` | integer | no |  |
| `per_thousand` | numeric | no |  |

#### `maps`

*MAPS · `003_maps.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `map_id` | integer | no |  |
| `name` | text | no |  |

#### `meta_snapshots`

*META · `004_meta.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `snapshot_id` | integer | no |  |
| `captured_at` | timestamp with time zone | no |  |
| `queue` | text | no |  |
| `platform` | text | no |  |
| `input` | text | yes |  |
| `patch_id` | integer | yes | `patches.patch_id` |
| `season_id` | integer | yes | `seasons.season_id` |

#### `patches`

*META · `004_meta.sql`*

The game versions the meta moves with. A win rate is true of a patch, so a snapshot records which patch was live when it was captured. Pulled from the wiki's Patches cargo table (pull_patches); name is the wiki's own page name, since Blizzard ships most balance patches unversioned.

| column | type | null | references |
| --- | --- | --- | --- |
| `patch_id` | integer | no |  |
| `name` | text | no |  |
| `released` | date | no |  |
| `platform` | text | yes |  |
| `url` | text | yes |  |

#### `perk_ability_effects`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `perk_id` | integer | no | `perks.perk_id` |
| `ability_id` | integer | no | `abilities.ability_id` |

#### `perk_stats`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `perk_stat_id` | integer | no |  |
| `perk_id` | integer | no | `perks.perk_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `value` | numeric | yes |  |
| `unit_numerator` | text | yes |  |
| `unit_denominator` | text | yes |  |
| `denominator_value` | numeric | yes |  |
| `condition` | text | yes |  |
| `value_text` | text | no |  |
| `raw_value` | text | no |  |

#### `perk_tiers`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `tier_id` | smallint | no |  |
| `code` | text | no |  |
| `name` | text | no |  |
| `unlock_level` | smallint | no |  |

#### `perks`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `perk_id` | integer | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `tier_id` | smallint | no | `perk_tiers.tier_id` |
| `name` | text | no |  |
| `description` | text | no |  |
| `position` | smallint | no |  |

#### `playstyle`

*PLAYBOOK · `005_playbook.sql`*

Which playstyle a hero belongs to, straight from the wiki's team composition page. The style vocabulary (dive, brawl, poke) is whatever the page says, kept as text rather than a three-row lookup table: the page is the vocabulary, and a new style there should load, not break.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `style` | text | no |  |

#### `regions`

*META · `004_meta.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `region_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |

#### `roles`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `role_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |
| `icon_url` | text | yes |  |

#### `schema_migrations`

*foundation · `008_schema_migrations.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `filename` | text | no |  |
| `applied_at` | timestamp with time zone | no |  |

#### `seasons`

*META · `004_meta.sql`*

Seasons: the coarser delineator. A patch tweaks numbers; a season swaps the hero pool and map rotation, so a snapshot records both. Pulled from the wiki's Season pages (pull_seasons): every season that has started, with its start date; note is the wiki subpage it came from. Reloaded whole; every rates snapshot is restamped with its season.

| column | type | null | references |
| --- | --- | --- | --- |
| `season_id` | integer | no |  |
| `name` | text | no |  |
| `started` | date | no |  |
| `note` | text | yes |  |

#### `sources`

*foundation · `001_initial_schema.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `code` | text | no |  |
| `name` | text | no |  |
| `url` | text | no |  |

#### `stage_terrain`

*MAPS · `021_stage_terrain.sql`*

A stage's terrain, counted in the map's wiki article (pull_terrain) with map_terrain's features and patterns. A stage's text: every kept section under a heading that names the stage, and every paragraph or list item elsewhere that names it and no other stage. A Hybrid phase's text: every Assault or Escort section, attack and defense together; where the article names the route's stretches, the first is the capture point's and the rest the payload's. A stage with 20 words of text or more holds all eight rows, zeros included; a stage with less holds none. Reloaded whole with map_terrain.

| column | type | null | references |
| --- | --- | --- | --- |
| `stage_id` | integer | no | `map_stages.stage_id` |
| `feature` | text | no |  |
| `mentions` | integer | no |  |
| `per_thousand` | numeric | no |  |

#### `stat_keys`

*HEROES · `002_heroes.sql`*

The stat vocabulary. `unit` is the canonical unit for the stat, used when a value carries no unit of its own ("damage = 90" is 90 hp).

| column | type | null | references |
| --- | --- | --- | --- |
| `stat_key_id` | integer | no |  |
| `code` | text | no |  |
| `label` | text | no |  |
| `unit` | text | yes |  |

#### `strategies`

*INFERENCE · `010_constraints_and_heuristics.sql`*

The mirror of the playbook: one row per markdown file in inference/strategies/ - its kind (constraint | heuristic | assumption, the last added by 013), the frontmatter a machine scores by (metric, direction, weight, expressions, params) and the prose body a person argues with. Reloaded whole by load_authored so a recommendation can cite the ids it was scored under; the files remain the truth.

| column | type | null | references |
| --- | --- | --- | --- |
| `strategy_id` | text | no |  |
| `name` | text | no |  |
| `kind` | text | no |  |
| `category` | text | no |  |
| `direction` | text | yes |  |
| `metric` | text | yes |  |
| `weight` | numeric | yes |  |
| `expression` | text | yes |  |
| `params` | text | yes |  |
| `body` | text | no |  |
| `playbook` | text | no |  |

#### `subroles`

*HEROES · `002_heroes.sql`*

The ten subroles, each belonging to exactly one role, each carrying the passive it grants (e.g. "Tactician: Store excess ultimate charge.").

| column | type | null | references |
| --- | --- | --- | --- |
| `subrole_id` | integer | no |  |
| `role_id` | integer | no | `roles.role_id` |
| `code` | text | no |  |
| `name` | text | no |  |
| `passive_description` | text | no |  |
| `icon_url` | text | yes |  |

#### `synergies`

*PLAYBOOK · `005_playbook.sql`*

Which heroes work WITH which. Pulled from the Synergy section of every hero's wiki article (pull_synergies): a pair per hero linked in another hero's section. score is 2 when both articles name each other, 1 when one does; note is the wiki's advice for the pair, cut to one clause. Bidirectional, unlike counters: each pair is stored once, lower hero_id first, and read from either side. Reloaded whole.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `other_id` | integer | no | `heroes.hero_id` |
| `score` | smallint | yes |  |
| `note` | text | yes |  |

#### `weapon_config_slots`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `slot_id` | smallint | no |  |
| `code` | text | no |  |

#### `weapon_configs`

*HEROES · `002_heroes.sql`*

weapon_type lives here rather than on the weapon because it varies by config: Ana's Biotic Rifle is a projectile from the hip and hitscan in ADS.

| column | type | null | references |
| --- | --- | --- | --- |
| `config_id` | integer | no |  |
| `weapon_id` | integer | no | `weapons.weapon_id` |
| `slot_id` | smallint | no | `weapon_config_slots.slot_id` |
| `name` | text | no |  |
| `weapon_type` | text | yes |  |
| `position` | smallint | no |  |
| `keywords` | text | yes |  |

#### `weapon_stats`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `weapon_stat_id` | integer | no |  |
| `config_id` | integer | no | `weapon_configs.config_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `value` | numeric | yes |  |
| `unit_numerator` | text | yes |  |
| `unit_denominator` | text | yes |  |
| `denominator_value` | numeric | yes |  |
| `condition` | text | yes |  |
| `value_text` | text | no |  |
| `raw_value` | text | no |  |

#### `weapons`

*HEROES · `002_heroes.sql`*

One row per weapon. A weapon's firing modes are configs, not weapons: Ana carries one Biotic Rifle, fired from the hip or down the sights.

| column | type | null | references |
| --- | --- | --- | --- |
| `weapon_id` | integer | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `name` | text | no |  |
| `position` | smallint | no |  |
<!-- /generated:dictionary -->
