# data - the DATA LAYER

Pull every source, clean it, store it in Postgres, and serve the tools
that do so. This is the layer that owns `FACTS = HEROES ∪ MAPS ∪ META`:
what the sources say about the heroes, the maps and the meta, pulled and
set. Any data in the database is just data - every row carries a
`source_id`, and that is the only distinction drawn between what was
measured, what was judged and what was written by hand.

**One door.** The MCP tools in `mcp/tools.py` are the only way in. A
Claude Code session calls them over MCP, the `refresher` container calls
them in-process, Docker's entrypoint calls them to build the database, and
a shell calls them the same way:

```bash
.venv/bin/python -m data.mcp list                        # the tools
.venv/bin/python -m data.mcp call db_rebuild             # build from scratch
.venv/bin/python -m data.mcp call sync_all               # update everything
.venv/bin/python -m data.mcp call pull_rates '{"refresh": true}'
```

There is no orchestrator, no per-module script, and nothing to keep in
step with the tools.

## Layout

```
data/
  README.md          this file
  __init__.py        the package's own map, in one docstring
  common.py          the plumbing every layer shares
  sources.py         the fetch cache and its freshness policy; the scope
  names.py           matching hero, map and ability names across sources
  playbook.py        the authored CSVs, reloaded whole
  refresh.py         the daily refresh (the refresher container's process)
  blizzard/          overwatch.blizzard.com, page to table
  wiki/              overwatch.fandom.com, page to table
  counterpick/       counterpick.gg, page to table
  mcp/               the MCP server and the tools
  db/                the schema: migrations, the ledger, rebuild, restore
  authored/          the inputs we write by hand
  raw/               one CSV per table, the mirror (exported, gitignored)
```

### The modules at the top

| file | purpose |
| --- | --- |
| `common.py` | Where the repo, the caches, the authored inputs and the mirror live; how the database is found (`DATABASE_URL`, or the embedded cluster at `db/cluster`); how a source registers itself and how names look up ids; the CSV export and its `EXPORT.json` mark naming the database it came from. Knows no particular source or table. |
| `sources.py` | `cached_get`: one page, from the cache if it is there and fresh. `set_max_age`: the freshness policy - a build keeps every cached page, the refresh refetches them, and a page that fails to refetch keeps its cached copy. `session`: a requests session that says who we are. The project's scope - console, controller, Americas - declared once. `AUTHORED`: the `sources` row for what we write instead of fetch. |
| `names.py` | `name_key` recognises the same hero or map across sites ("Lúcio", "Lucio"; "D.Va", "DVa") by folding accents and punctuation. `ability_key` recognises the same ability across Blizzard and the wiki by dropping one trailing parenthetical. Two keys because they solve two problems. |
| `playbook.py` | Loads `authored/*.csv` - seasons, synergies, archetypes, map playstyles - each a whole-truth reload with loud errors on a malformed row or an unknown name. The `load_playbook` tool runs them, then mirrors the strategies catalog. |
| `refresh.py` | The clock. Daily at `OVERWATCH_DB_REFRESH_AT` it refetches what moves between patches (rates, counters), re-mirrors the playbook and the strategies, re-exports the mirror; once the wiki cache is older than `OVERWATCH_DB_REFRESH_FULL_DAYS` it runs `sync_all` on every source. Refreshes on start when the caches are older than a day. |

### One package per source

Each source package owns the whole path from page to table. Its
`__init__.py` names the endpoints, the `sources` row its pages become and,
for the wiki, the client that talks to the MediaWiki endpoint. Each domain
module is one `run(connection, cache_dir, session, log)` the tools call:
fetch (cached), extract the values from the markup, normalise them, store
them.

| package | module | stores |
| --- | --- | --- |
| `blizzard/` | `heroes.py` | the roster: heroes, roles, subroles, portraits and icons, ability and perk text. Runs first; everything links to heroes. Blizzard publishes prose and no numbers. |
| | `meta.py` | win, pick and ban rates as a dated snapshot, sliced by skill tier and by map. Competitive Role Queue (the page offers no Open Queue), console, Americas - all recorded on the snapshot. |
| `wiki/` | `heroes.py` | hero kits from the Cargo Abilities table: weapons and their firing configs, abilities, perks, keywords, and every stat as a measurement. Supplements the interaction flags from article wikitext. Runs after `blizzard.heroes`. |
| | `maps.py` | maps, game modes and stages from the Maps article's Standard Play section. |
| | `patches.py` | game versions from the Patches cargo table; snapshots link to the patch current at capture. Runs before the rates pulls. |
| | `playstyles.py` | the team-composition playstyles (dive, brawl, poke) and the heroes listed under each. |
| | `markup.py` | reading the wiki's two markups - Cargo's rendered HTML and article wikitext - and the tidying both need; the link pattern. |
| | `measurements.py` | a stat value ("75 over 0.59 seconds", "10 - 20 meters", a yes/no glyph) into value, unit, window and condition. |
| | `weapons.py` | the wiki's one-entry-per-firing-mode list grouped into weapons and their configs. |
| | `modifiers.py` | what a buff scales and who it lands on, recovered from the value's wording and the ability's keywords. |
| `counterpick/` | `heroes.py` | who counters whom, best maps, and the site's own win and pick rates as their own snapshot (a different population from Blizzard's). Runs after `wiki.maps` and `blizzard.meta`. |

### `mcp/` - the door

| file | purpose |
| --- | --- |
| `server.py` | A dependency-free MCP server: JSON-RPC over stdio, and the same surface over Streamable HTTP (`POST /mcp`, `GET /health`). `initialize`, `tools/list`, `tools/call`, `resources/*`. Dependency-free because the official SDK needs Python 3.10 and the project runs on 3.9. |
| `tools.py` | The tools. `pull_*` (one source and domain each), `load_playbook`, `sync_all`; the database's life (`db_status`, `db_init`, `db_migrate`, `db_rebuild`, `export_csv`, `db_docs`, read-only `query`); and, through the same door, the user and inference layers' tools (`roster`, `facts`, `infer`, `evaluate`, `board`, `strategies`, `record`, `record_outcome`, `tune`, `fit_weights`, `tuning_log`). The strategies are also served as `strategy://` resources. |
| `__main__.py` | `python -m data.mcp` serves over stdio (what `.mcp.json` launches); `--http HOST:PORT` serves over HTTP (the `data` container); `list` and `call NAME [JSON]` are the shell. |

### `db/` - the schema

| file | purpose |
| --- | --- |
| `schema.py` | Applies migrations and records them in the `schema_migrations` ledger; `pending` says which files the database has not seen; `rebuild` drops everything and reapplies; `restore` brings recorded recommendations and outcomes back from the mirror after a rebuild; `generate_docs` writes `docs/erd.md` and `docs/data-dictionary.md` from the live schema. |
| `migrations/` | The schema as a sequence, one file per step: `001` sources and the foundation, `002` heroes, `003` maps, `004` meta, `005` playbook, `006` inference, `007` the three layers, `008` the ledger, `009` outcomes, `010` constraints and heuristics (the `strategies` table). A migration is never edited once applied; a change is a new file, and a populated database catches up with `db_migrate`. |
| `cluster/` | The embedded Postgres cluster `pgserver` creates on first touch (gitignored). The compose stack uses its own `postgres` container instead, reachable from the host through `./docker-db`. |

### `authored/` - what we write

The inputs that are ours rather than fetched: `synergies.csv`,
`archetypes.csv`, `map_playstyle.csv`, `seasons.csv`, each documented in
[`authored/README.md`](authored/README.md), and `recommendations/`, one
markdown transcript per recorded composition. They are committed, loaded
whole-truth by `load_playbook`, and never discarded by a rebuild. The
strategies themselves - the constraints and heuristics - are not here;
they are the inference layer's, in `inference/strategies/`.

### `raw/` - the mirror

One CSV per table, exported by `export_csv` after every sync and every
recorded comp, plus `EXPORT.json` naming the database that exported it.
Gitignored. Two things read it: `restore` after a rebuild (the one thing no
tool can re-fetch is never discarded), and the parity tests, which skip
themselves when the mirror came from the other database.

## The order of a build

`sync_all` runs the pulls in dependency order - `blizzard.heroes`,
`wiki.heroes`, `wiki.maps`, `wiki.patches`, `blizzard.meta`,
`wiki.playstyles`, `counterpick.heroes` - then `load_playbook`, then
`restore`, then `export_csv`. Entity tables refresh in place; each rates
pull appends a dated snapshot, the series the trend facts difference. The
page caches (`.cache-blizzard/`, `.cache-wiki/`, `.cache-counterpick/` at
the repo root) make every build after the first cost almost no requests.
