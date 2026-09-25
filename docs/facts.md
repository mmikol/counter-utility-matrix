# The FACTS LAYER - `facts/`

Everything the database knows about a board, and the one definition of
every metric: the World, the database in memory, loaded per request; the
metrics registry, the vocabulary a strategy may name; the FactSet, every
fact about one board, numbered for citation. The board shows these facts,
the solver scores the same functions and the door serves them as tools,
so the number on the board and the number the solver maximises cannot
drift. The layer reads the database, writes nothing and imports only `db`.

It owns FACTS, the left-hand side of the equation in
[architecture.md](architecture.md): for each domain, the independent
facts (one selection's own row, which no other selection changes) and the
dependent ones (that selection joined with others - `map_meta` is heroes
⋈ maps ⋈ meta, `counters` and `synergies` are heroes ⋈ heroes, the team
facts aggregate the six, the matchup facts compare the twelve, the ban
facts join a banned hero with both teams' counters). A join belongs to
every domain it touches, and every selection added opens new joins.

## Layout

```
facts/
  __init__.py      the package's map
  model.py         the World: the database in memory, per request
  tables.py        the load: every table read into a World, the maps' styles, the best maps
  scalars.py       a hero's numbers derived from its kit, one step per section
  kit.py           a kit piece's stat rows and the combat numbers read off them
  records.py       the typed records a Hero, a Map and the World hand on
  draft.py         the board's vocabulary and the Draft record the doors read
  roster.py        the roster: every hero and map the board tools accept
  team.py          the team metrics and the typed bag every metric section comes in
  compute.py       the matchup, map and world metrics, and the registry of them all
  factset.py       the FactSet: a board's facts, numbered and filed by metric
  board_facts.py   generate(): every fact for a board, written into a FactSet
  hero_facts.py    a named hero's facts: the kit, the rates, this board's own
  team_facts.py    a team's facts, one per team metric, and the matchup's
```

## The modules

### `kit.py` - the kit and its numbers

A `Kit` is an ability, a weapon config or a perk; a `Stat` is one of its
measurements as the data layer stored it - a value in its units, under a
condition - with the wiki's original words beside it. `rate(code,
per_shot)` is a piece's sustained rate: the published rate with the reload
the wiki words beside it, else the firing rate over its magazine and
reload, else one shot times the fire rate. `hits()` and `cast_hit()` are
the single hits a hero's burst is read from, `ult_hit()` one ultimate
cast's damage, `reach` how far a weapon fights, `dual_rate` two guns fired
from one magazine. This is the one place the wiki's prose is read:
`db/data/wiki/kits/measurements.py` splits a stat into measurements at ingest
and keeps its text, and the wording rules - a reload in a row's text, a
figure that is a sum, an overhealth percent worth its cap - live here, so a
misread stat is fixed in this file and needs no re-pull.

### `model.py` - the World

The World holds what `tables.load` read. A `Hero` is a dataclass built by
keyword: its fields state its whole shape at rest, so a hero the rows
never filled reads zero, and a test builds one with any field set. A
hero's `derive_rates()` reads its rank spread and trend off the rates, and
`cap_ult(cap)` caps its ultimate's damage at the roster's largest single
figure. A map's `style_top` is the highest of its styles, ties by name;
`style_margin` is the top minus the runner-up. `resolve(map, red, blue,
bans)` turns names into a `Resolved` - the map and the red, blue and
banned heroes - through the same name matching the data layer uses, and
refuses a banned pick, an unknown hero, or a hero on both teams.

### `records.py` - the typed records

What a Hero, a Map and the World hand to the metrics, the facts engine and
the solver, each shape declared once: a hero's `Modifier`s, `PerkEffect`s,
`Rates` per tier and `MapRate` per map; a stage's `StageTerrain` and a
map's `StyleScore` per playstyle; the World's `Synergy` pairs, `Snapshot`
provenance and the `Patch`es newer than the rates. `Snapshot` is a
TypedDict and the rest are NamedTuples, so a reader that unpacks one still
does.

### `tables.py` - the load

`load(cx)` reads every table into one World, once per request, from an
open psycopg connection it never opens itself: the heroes (role, subrole,
health/shield/armor, the kit - weapons with their firing configs,
abilities, perks, every stat as a measurement with unit and condition -
keywords, the latest and previous rates, the per-map and per-tier rates,
counters both ways, playstyles), the maps (mode, stages, terrain), the
meta snapshots and the patches newer than the capture, synergies and
partners, the catalog's shape. One read step fills each part, and `load`
runs them in the order they rely on. `map_styles` then derives each map's
styles: for a playstyle, the mean over the released heroes tagged with
it - each weighted 1/(its tag count) - of the hero's win rate on the map
minus its overall win rate, z-scored across the maps. `best_maps` derives
each hero's best maps: the three with the largest map win rate minus
overall win rate, only where positive, ties by map name. A test in
`tests/facts` insists every data table is read here: a table nothing
reads is not data.

### `scalars.py` - a hero's numbers

`derive_scalars(hero)` derives the hero's numbers from weapons, abilities and
passives; ultimates add tools only, perks nothing. It runs one step per
section, in order, each setting its own fields on the hero: the body
(pool, keywords, a form's armor, cooldowns); dps, the held weapon
sustained with its reload in; burst, the biggest single hit, a headshot
where one counts; healing - hps and peak heal onto teammates, per second
and per cast, self-heal apart - the one step that reads an earlier
result, dps; reach, the weapons' published range or falloff, unknown
staying out; then the weapon kinds, area, barriers, amps and anti-heal,
crowd control and mobility, cleanses and saves, and the ultimate - so the
metrics read fields, not SQL. The ultimate's raw damage waits for
`cap_ult`, which the load calls once the roster's cap is known.

### `draft.py` - the board's vocabulary

The names every layer spells a board with: `TEAM_SIZE` (six, 6v6 Open
Queue), `MAX_TANKS` (two, the queue's own limit, whatever the playbook
holds), `MAX_BANS` (five), `EXPECTED_SHAPE` (two per role), `SIDED_MODES`
(Escort, Hybrid), `SIDES`, `is_sided` and `opposite`; `check_team_size`
and `check_tanks` refuse a team past the first two. `Draft`, a frozen
dataclass, is the board at one stage of the pick-and-ban draft - the map,
red's and blue's picks, the bans and blue's side, in that order, each list
a tuple. Wherever a Draft is built, `dataclasses.replace` included, it
refuses a team of seven, a sixth ban and a side that is not one, so the
page, the inference service and the MCP board tools refuse the same
boards. A playbook draft is another thing: a strategy that awaits its
frontmatter. `parse_board(query)` reads a Draft off a `Query`, a parsed
query string, dropping empty values: the one reader of a board off the
wire, shared by the page and the inference service because the page's
board runs through `serve.handle_board`. Both take `Query` from here. The
module imports only the model and `db.Refusal`, so the metrics can take
its names without a cycle.

### `roster.py` - the roster

Every hero and map the board tools accept, built once for both readers:
the board's `/api/roster` and the door's `roster` tool. `roster_of(world)`
returns a `Roster` - the heroes as `RosterHero` records in role order
(role, subrole, health pool, portrait, status, and the release day of an
announced hero), the maps as `RosterMap` records in name order (mode, the
style it rewards most, `Map.style_top`, and whether it is sided, from
`is_sided`). The page reads the maps' styles and sides and ignores the
pool; the tool's text lists each map with its mode, style and side.

### `team.py` - the team metrics

Pure functions over a World, and the one place a team's number is
defined. `TEAM_METRICS` is the registry of `team.*` keys, each with a
one-line meaning; a strategy reads the same keys for red as `enemy.*`.
`team_metrics(world, heroes, map, enemies)` computes a team's bag, one
helper per registry section - shape (`tanks`, `damage`, `supports`,
`shape_flags`), durability (`pool_total`, `squish_count`), damage
(`dps_floor`, `burst_max`, `one_shots`), sustain (`hps_supports`,
`hps_ratio`, `heal_peak_max`), tools (`mobility_count`, `cc_count`,
`barrier_count`), cohesion (`synergy_score`), meta (`win_mean`,
`availability`), map fit (`map_specialists`, `home_map_hits`) and
versus, the coverage of the enemy (`coverage_share`) - each writing its
keys once and in registry order. Beside them rides `_answered`, the
answering picks per enemy the facts engine words; the solver asks for
the bag `lean=True`, which leaves it empty. `MetricBag` is the shape every
metric section comes in: a dict of `MetricValue`, a count or figure, a
name, a name list, the `SynergyPair`s, the style tally or the answers.
`number`, `text`, `names` and their siblings read a value as the kind a
caller needs and refuse any other, so a text metric never reaches
arithmetic unnoticed.

### `compute.py` - the metrics registry

The other three registries and the functions behind them, and the one
list of every key a strategy may reference: `registry()` gathers
`TEAM_METRICS` (as `team.*` and `enemy.*`) with its own, and
[inference.md](inference.md) prints them as the vocabulary. The board
renders them as facts and the solver scores the same functions, so a
change here or in `team.py` changes both.

| group | examples |
| --- | --- |
| `team.*` (also read as `enemy.*`) | see `team.py` |
| `matchup.*` | the differences and ratios between the two teams: `dps_diff`, `burst_vs_heal`, `tempo_diff`, `exposure_share`, `ult_answers` |
| `map.*` | `known`, `mode`, `sided`, `side`, `style_top`, `style_margin`, `stages`, `bans` |
| `world.*` | `heal_bench`, `hps_bench`, `roster_size` |

`matchup_metrics(blue, red)`, `map_metrics(map, side, ban_count=...)` and
`world_metrics(world)` compute the rest; `namespace(...)` bundles a
board's bags as the `team`, `enemy`, `matchup`, `map` and `world`
sections a strategy's expression reads. `expected_picks` is red's likely
six from the data alone, filled into `EXPECTED_SHAPE` (two per role) with
a tie going to the alphabetically first name, each pick an `ExpectedPick`
record.

### `factset.py` and `board_facts.py` - the FactSet

`generate(world, draft)` walks the board a `Draft` names and numbers what
it finds. Facts are structured (scope, subject, key, value, unit,
source) so the inference layer reads them by key, and rendered as
sentences so a person - or the `/comp` session - reads them as evidence:

```
[F1]  blizzard rates captured 2026-09-13 under Patch 14.3 ...      meta
[F7]  Widowmaker is banned: 2 red pick(s) it would have answered    bans
[F12] King's Row is Hybrid; blue attacks, red defends              map
[F40] Zarya's weapon sustains 95 damage per second                 hero
[F210] blue team shape: 2 tank / 2 dps / 2 support                 team
[F230] sustain war: red supports peak 165 heal vs 1 blue anti-heal matchup
-- the playbook's record: what it holds - not facts --
[S1]  the playbook holds ... constraints, ... heuristics and ...   playbook
```

Independent facts per hero and for the map come first; joint facts per
team appear once a team has picks; matchup facts once both teams do. Ids
are dense and stable within a board, which is what makes a citation mean
something. Below the facts, numbered S1.., rides the playbook's record -
how many constraints, heuristics and assumptions the catalog holds -
citable but never mistaken for data, and not the strategies themselves.

`factset.py` is the record: a `Fact`, frozen once numbered, and the
`FactSet` that numbers them, keeps the `Draft` they describe with its
names resolved, and files each fact under every metric its sentence
states, so `find(key)` is every fact stating that metric and a subject
narrows it. The writers are three modules: `board_facts.py` holds
`generate()` and the meta, bans, map and playbook writers,
`hero_facts.py` a named hero's, and `team_facts.py` each team's and the
matchup's.

## What reads `facts/`

`facts/` is read by the board, the inference layer, the door and the
reach recorder, all through the same functions:

| reader | what it imports from `facts/` |
| --- | --- |
| the board (`ui/board.py`, `ui/pages.py`) | `tables`, `board_facts`, `draft`, `roster` |
| the objective and the scale (`inference/scoring.py`, `inference/scale.py`) | `compute`, `team`, `model` |
| the shapes (`inference/shapes.py`) | `draft` |
| the search (`inference/solver.py`) | `model` |
| the engine (`inference/engine.py`) | `board_facts`, `compute`, `factset`, `model`, `draft` |
| the result and plan records (`inference/result.py`, `inference/plan.py`) | `factset`, `team`, `model`, `draft` |
| the pool and reach (`inference/parallel.py`, `inference/reach.py`) | `model`, `draft` |
| the catalog's checks and the deriver (`inference/strategy.py`, `inference/catalog.py`, `inference/derive.py`) | `compute` - the metric vocabulary |
| the inference service (`inference/serve.py`) | `tables`, `draft` |
| the door's `roster`, `facts`, `infer`, `evaluate`, `reach` and `board` tools (`door/mcp/facts.py`, `door/mcp/solver.py`, `door/mcp/boards.py`) | `tables`, `board_facts`, `draft`, `roster` |
| the door's `metrics` tool (`door/mcp/playbook.py`) | `compute` - the metric vocabulary |
| the reach recorder (`scripts/reach.py`) | `tables` |
