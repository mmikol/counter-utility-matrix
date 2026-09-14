# The UI LAYER - `ui/`

The board in front of you, and the facts behind it. Every click - a map,
a side, a ban, a hero on either roster - becomes a request, the database
is read, and three things come back: every fact about that board, the
optimal six for both seats with the current picks scored, and the
playbook as it sits on disk. This layer reads, and has one write - a
heuristic's weight stored from its slider - which it hands to the data
layer's `tune` tool rather than making itself; the data layer owns every
write, and the inference layer owns the scoring. What it owns is
the equation's left-hand term:

```
DATA           = HEROES ∪ MAPS ∪ META              the tables, as pulled and set
for each domain D in { HEROES, MAPS, META }:
  INDEPENDENT(D) = ⋃ facts(s)      over each selection s in D    s alone: its own row
  DEPENDENT(D)   = ⋃ facts(s ⋈ t)  over the other selections t   s joined with t, in D or beyond
  FACTS(D)       = INDEPENDENT(D) ∪ DEPENDENT(D)
FACTS          = FACTS(HEROES) ∪ FACTS(MAPS) ∪ FACTS(META)
FACTS(D) ∩ FACTS(E) = the joins of D with E: what only their intersection can say
```

Every domain yields both kinds. An independent fact is one selection's
own row, and no other selection changes it. A dependent fact is that
selection joined with others - `map_meta` is heroes ⋈ maps ⋈ meta,
`counters` and `synergies` are heroes ⋈ heroes, the team facts aggregate
the six joined, the matchup facts compare the twelve, the ban facts join
a banned hero with both teams' counters - and a join belongs to every
domain it touches, so the dependent facts are where the domains' fact
sets intersect. Every selection added opens new joins.

```bash
.venv/bin/python -m ui.board              # http://localhost:8017, the local cluster
INFERENCE_URL=http://localhost:8019 .venv/bin/python -m ui.board   # comps from the service
```

Standard library only: an `http.server` handler, no framework, no build
step. In the compose stack the `ui` container runs the same module with
`INFERENCE_URL` pointing at the `inference` container, so the board
computes facts in-process and asks the service for comps.

## Layout

```
ui/
  __init__.py      the package's map
  board.py         the page, its JSON endpoints, the math page
  static/
    board.css      the look: the game's hero select, dark, red and blue
    board.js       the behaviour: state, fetches, the ban picker, the three panels
  facts/           everything the database knows about a board
    model.py       the World: the database in memory, per request
    compute.py     the metrics registry: every number, one function each
    engine.py      the FactSet: the numbered facts for a board
```

## `board.py` - the page and its endpoints

The page is a shell: the stylesheet and the script are static files, and
`TEAM` (six) and `BANS` (five) are the only values the page injects, so
the script has no constant to keep in step with the Python.

| route | serves |
| --- | --- |
| `/` | the board: map selector, attack/defense switch (Escort and Hybrid maps), the bans bar (a collapsible picker of the same portrait tiles, up to five, all optional), the red and blue rosters grouped by role with the announced hero at the end, and three panels - **comps**, **facts**, **playbook** |
| `/static/<file>` | `board.css` and `board.js` |
| `/api/roster` | every hero (role, subrole, portrait, icon) and every map (mode, sided or not) - what the rosters are built from |
| `/api/facts?map=&side=&red=&blue=&ban=` | the FactSet for the board, as JSON: the facts, their count, and the playbook's record |
| `/api/infer?map=&side=&red=&blue=&ban=` | the board solved at any stage: blue's optimal (the counter to red's selection), red's optimal (their counter to yours), both current comps on those scales, blue's picks against red's best counter, the empty blue slots filled, the momentum verdict and the game plan - the inference layer's `board()` in-process, or the service's `/board` when `INFERENCE_URL` is set |
| `/api/strategies` | the strategies catalog: every constraint and heuristic with its kind, form, frontmatter and body |
| `/math` | the equation and how the layers fit, in prose - linked from the board's header |

Every request opens its own connection and loads a fresh World, so a
`pull_rates` or a tune shows on the next click without a restart.

## `static/` - the board's look and behaviour

`board.js` keeps one piece of state - the map, the side, the bans, the
red picks, the blue picks - in `localStorage`, so a reload mid-game keeps
the board. A click on a portrait toggles that hero on that team (a banned
hero cannot be picked; a hero on one team cannot be on the other); a
change debounces, then fetches facts and inference together.

**The rosters.** One tile renderer draws the red roster, the blue roster
and the ban picker, so all three read as the same hero select: portrait
tiles in tank, damage and support columns, lit when picked, dotted when
on the other team, crossed out when banned, and dimmed once the
playbook's shape limits leave no legal six that seats one more of that
role - the board result carries the `(tanks, damage, supports)` triples
the hard limits allow, the column header says the cap when there is one
(`max 2` over the tanks), and a click on a dimmed tile is refused with a
note rather than sent; both teams are held to it, since the limit is the
game's form and not blue's alone. A hero the roster carries as
**announced** - one the wiki knows ahead of release, with its role,
subrole, health, kit and release day - sits in its own role column as
the same tile, dimmed, tagged "coming soon", its portrait when the wiki
has one and a silhouette otherwise, and with no click handler: it never
enters the state, so it is never sent as a pick, and the solver never
fields it. Blizzard listing the hero flips it to released and the tile
comes alive on the next refresh.

**The bans bar.** Collapsed by default: a header with the count and the
current bans as small portraits (click one to un-ban). Clicking the header
opens the picker - the five slots (two red, two blue, the lobby's) above
the same portrait grid the rosters use. A click on a tile bans that hero,
which leaves both rosters and the search; a click on a banned tile or on
its slot un-bans it; at five, the rest dim.

**The panels.** *comps* is the default, and it answers at every stage
of a draft: no map (the meta's best six), a map, a map and a side, bans,
red's picks as they reveal. On top, the game plan in prose: the ground
(the mode's geometry and the authored note on what the map rewards), the
side, what to play and how, what red's picks mean and which of the six
answer them, the family of heroes to stay in when you stray from the six,
and what the six is built for - from the same facts and strategies the
solver scored, so picks can be tailored toward the optimal without
matching it; a last line says what it rests on. Then, in the order of
the boxes above, blue's optimal six (left: the counter to red's
selection as revealed, whatever you have locked, so it never collapses
into your own six) and red's comp as revealed (right, scored against
yours on the scale of their best counter). Every score says what it
means under the number: 100 is the best six the solver can build for
this board, and any other comp's number is its score as a share of that
best; the momentum strip states the scale once and links to the math.

The scores live with the selections. Above the two boxes sits the
momentum strip: the verdict from the two current comps, each on its own
optimal's scale - your picks as a share of blue's best counter to red's
selection, red's as a share of their best counter to yours - and, when
you have picks, how you hold if red answers you perfectly. Each box
carries its own share as a badge by its name - the current comp's while
the seat holds picks, the suggested six's (its optimal, 100 by
definition) before any pick, or *unscored* with the reason - and a
*clear* button that
empties that team's picks; *clear all* in the header empties everything -
the map, the side, the bans and both teams. Red's box only holds and
scores what they reveal; the blue box also fills its empty slots with the
solver's suggestions - the optimal six before any pick, then the best six
that keeps what you have locked - each a click away from locking. The
tile shows the hero alone; its reasons are the tooltip and the comps tab.
The comp is
full width below. Each result shows one figure, its 0-100 share
(`normalized`: 100 for an optimal six, the current comp's share of blue's
optimal on that board) with its meaning beside it; the raw sum is never
shown. It reads *unscored* instead - in the team badges, the results and
the momentum strip - when nothing can be a share of anything: the
playbook in force has no heuristic, scored constraint or soft limit, or
none of them applies to this board yet (a heuristic waiting on its
`when`), and the engine's reason (`unscored` on each result, naming the
strategy that waits and what for) sits where the meaning would; then
each pick
with its reasons and `[F#]` citations, the strategies satisfied (one bar
per strategy, headed by the count met, greyed where a strategy did not
apply to this comp), the
alternatives (each with its own 0-100 figure when present) and the partial
notice. *facts*
filters by text and by scope (meta, bans, map, hero, team, matchup,
playbook), and says how many it holds beside the filter - "464 facts",
or "12 of 464 facts" while a filter narrows it; the tab itself carries
no number. *playbook* renders the catalog in three groups in the
equation's order - constraints, heuristics, assumptions - each headed
with its count and a line on what the kind does, an empty group saying
so, every card edged in its kind's colour; a card shows its form,
and under each heuristic a slider for its weight - 1 to 10 to the
hundredth (1.02, 9.99), with a number box beside it for the exact figure,
starting at the weight the file infers, with the inferred figure shown
and a reset. A setting is the viewer's alone: it is kept in the
browser, rides with every board request as `weight=<id>:<value>`, is
applied by the solver for that board only (each result reports the
`weights` it was scored under), and never touches the file - until
*store*, which writes it
into the heuristic's file through the data layer's `tune` tool (validated
against the catalog, logged in the tuning log with its reason, mirrored),
after which the file's weight is the inferred default and the browser's
setting is dropped. `POST /api/weight` `{id, weight}` is that one write;
it reaches the tool over HTTP at `COUNTER_MATRIX_MCP_URL` with the bearer
token in the compose stack, and in-process through the same registry on
the local cluster. Only heuristics have a weight to set. *clear all*
leaves the weights in place.
Pinned to the header's top-right
corner are two pills: *the math*, a page stating the equation and how
the layers fit, and the repository on GitHub (`COUNTER_MATRIX_REPO_URL`
overrides the address when the repo moves). A
footer at the very bottom carries the status - the facts on the board,
the playbook notes, the time of the last read - and the rates' capture
date and patch; the header keeps only the short-lived flashes (a banned
pick, a full team).
`board.css` is the game's hero select: role columns, portrait tiles, red
and blue seats, the dark palette.

## `facts/` - everything the database knows about a board

### `model.py` - the World

`load(cx)` reads every table into one object, once per request: the
heroes (role, subrole, health/shield/armor, the kit - weapons with their
firing configs, abilities, perks, every stat as a measurement with unit
and condition - keywords, the latest and previous rates, the per-map and
per-tier rates, counters both ways, best maps, playstyles), the maps
(mode, stages, playstyle fit), the meta snapshots and the patches newer
than the capture, synergies and partners, archetypes, the catalog's
shape. `Hero.finish()`
derives what the kit implies - peak damage and healing per second,
burst, mobility and crowd-control tools, hitscan, flight, anti-heal,
cleanse, barrier, effective HP - so the metrics read fields, not SQL.
`resolve(map, red, blue, bans)` turns names into objects through the
same name matching the data layer uses, and refuses a banned pick, an
unknown hero, or a hero on both teams. A test in `tests/ui` insists
every data table is read here: a table nothing reads is not data.

### `compute.py` - the metrics registry

Pure functions over a World, and the one place a number is defined. The
board renders them as facts and the inference layer's solver scores the
same functions, so the number on the screen and the number in the score
are the same function - a change here changes both. Four registries,
each key with a one-line meaning (`registry()` lists them all, and
[docs/inference.md](inference.md) prints them as the vocabulary a strategy may
reference):

| group | count | examples |
| --- | --- | --- |
| `team.*` | 92 | shape (`tanks`, `damage`, `supports`, `shape_flags`), sustain (`heal_peak_total`, `heal_ratio`), damage (`dps_floor`, `burst_max`), durability (`pool_total`, `squish_count`), tools (`mobility_count`, `cc_count`, `hitscan`, `antiheal`, `barrier_count`), coverage of the enemy (`coverage_share`), cohesion (`synergy_score`), map fit (`map_specialists`, `map_strategy_hits`), style (`style_lean`) |
| `matchup.*` | 21 | the differences and ratios between the two teams: `dps_diff`, `burst_vs_heal`, `tempo_diff`, `ult_threat`, `style_lean_red` |
| `map.*` | 7 | `known`, `mode`, `sided`, `side`, `style_top`, `style_margin`, `stages` |
| `world.*` | 2 | `heal_bench`, `roster_size` |

`team_metrics(world, heroes, map, enemies)` computes a team's numbers
(with `lean=True` for the solver, which skips the descriptive strings);
`matchup_metrics(blue, red)`, `map_metrics(map, side)` and
`world_metrics(world)` the rest; `namespace(...)` bundles them as the
`team`, `enemy`, `matchup`, `map` and `world` sections a strategy's
expression reads. `TEAM_SIZE` (six, 6v6 Open Queue), `SIDED_MODES`
(Escort, Hybrid), `SIDES`, `is_sided` and `opposite` live here too.

### `engine.py` - the FactSet

`generate(world, map, red, blue, bans, side)` walks the board and
numbers what it finds. Facts are structured (scope, subject, key, value,
unit, source) so the inference layer reads them by key, and rendered as
sentences so a person - or the `/comp` session - reads them as evidence:

```
[F1]  blizzard rates captured 2026-09-13 under Patch 14.3 ...      meta
[F7]  Widowmaker is banned: 2 red pick(s) it would have answered    bans
[F12] King's Row is Hybrid; blue attacks, red defends              map
[F40] Zarya (red): peak 190 dps, 200 barrier, ...                  hero
[F210] blue team: 2 tanks, 2 damage, 2 supports ...                team
[F230] sustain war: red supports peak 165 heal vs 1 blue anti-heal matchup
-- the playbook's record: what it holds - not facts --
[S1]  a brawl comp wants 2 tank: ...                               playbook
```

Independent facts per hero and for the map come first; joint facts per
team appear once a team has picks; matchup facts once both teams do.
Ids are dense and stable within a board, which is what makes a citation
mean something. Below the facts, numbered S1.., rides the playbook's
record - the archetypes, how many constraints, heuristics and assumptions
the catalog holds - citable but never mistaken for data, and not the
strategies themselves.

## One click on the board

```mermaid
sequenceDiagram
    actor You
    participant Board as ui/board.py
    participant Facts as ui/facts/ (World + FactSet)
    participant Solver as inference/ (solver)
    participant DB as PostgreSQL

    You->>Board: pick the map and your side, set the bans,<br/>click red picks as they reveal, lock your blue picks
    Board->>Facts: /api/facts (map, side, red, blue, bans)
    Facts->>DB: load the World (a dozen queries)
    Facts-->>Board: F1..Fn - every fact about those heroes,<br/>the map, each team, the matchup
    Board->>Solver: /api/infer (map, side, red, blue, bans)
    Solver->>Solver: blue's seat: shapes the limits allow · per-role pools ·<br/>every candidate scored · local search
    Solver->>Solver: red's seat, the other side: their best counter to your picks
    Solver->>Solver: both current comps: six locked -> ranked against the field;<br/>fewer -> scored with the optimal search's bounds
    Solver->>Facts: the FactSet for each (map, side, red, the six)
    Solver-->>Board: the game plan, the momentum, blue's optimal with reasons and [F#]<br/>citations, red's comp as revealed, the suggestions for the empty slots
```

Sides exist on Escort and Hybrid maps only; the rates do not split by
side, so the side reaches the score through two small scored constraints about the
kits (engage and anti-heal on attack, deployables, barriers and reach on
defense) and the facts say so.

## What reads this package

The inference layer's solver (`compute`) and engine (`engine`, `model`),
the inference service, and the MCP tools `roster`, `facts`, `infer`,
`evaluate` and `board` - all through the same functions the board calls.
