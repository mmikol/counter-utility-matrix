# The UI LAYER - `ui/`

The board in front of you, and the facts behind it. Every click - a map,
a side, a ban, a hero on either roster - becomes a request, the database
is read, and three things come back: every fact about that board, the
optimal six for both seats with the current picks scored, and the
playbook as it sits on disk. This layer reads; its one write, a
heuristic's weight stored from its slider, is handed to the data layer's
`tune` tool. It owns FACTS, the left-hand side of the equation in
[architecture.md](architecture.md): for each domain, the independent facts
(one selection's own row, which no other selection changes) and the
dependent ones (that selection joined with others - `map_meta` is heroes ⋈
maps ⋈ meta, `counters` and `synergies` are heroes ⋈ heroes, the team
facts aggregate the six, the matchup facts compare the twelve, the ban
facts join a banned hero with both teams' counters). A join belongs to
every domain it touches, and every selection added opens new joins.

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
    board.css      the look: the game's - dark surfaces, Bebas Neue headings, a gold accent, red and blue for the sides
    board.js       state, the rosters, the picks, the bans, the fetches, boot
    comps.js       the comps tab: a seat's result and the two seats
    playbook.js    the playbook tab: the groups, the cards, the weight sliders
    math.html      the math page's article
  facts/           everything the database knows about a board
    model.py       the World: the database in memory, per request
    compute.py     the metrics registry: every number, one function each
    engine.py      the FactSet: the numbered facts for a board
```

## `board.py` - the page and its endpoints

The page is a shell: the stylesheet and the scripts are static files, and
`TEAM` (six) and `BANS` (five) are the only values the page injects, so
the scripts have no constant to keep in step with the Python.

| route | serves |
| --- | --- |
| `/` | the board: map selector, attack/defense switch (Escort and Hybrid maps), the bans bar, the red and blue rosters grouped by role with the announced hero at the end, and three panels - **comps**, **facts**, **playbook** |
| `/static/<file>` | `board.css`, `comps.js`, `playbook.js`, `board.js` - the stylesheet and the scripts, nothing else |
| `/api/roster` | every hero (role, subrole, portrait, icon, status) and every map (mode, sided or not) - what the rosters are built from |
| `/api/facts?map=&side=&red=&blue=&ban=` | the FactSet for the board, as JSON: the facts, their count, and the playbook's record |
| `/api/infer?map=&side=&red=&blue=&ban=` | the board solved at any stage - the inference layer's `board()` in-process, or the service's `/board` when `INFERENCE_URL` is set: blue's optimal (the counter to red's selection), red's optimal (their counter to yours), both current comps on those scales, blue's picks against red's best counter, the empty blue slots filled, red's likely starting comp, the fight odds, the game plan and the shapes the limits allow |
| `/api/strategies` | the strategies catalog: every constraint, heuristic and assumption with its kind, form, frontmatter and body |
| `/math` | `static/math.html` in the page shell: the equation, the scoring function (what 100 means, fight odds, the argmax), the board (red's likely starting comp and its formula, blue's optimal counter, the weights) and how the layers fit, with a table of contents; linked from the board's header |
| `POST /api/weight` `{id, weight}` | the board's one write: a `tune` call, see the playbook panel below |

Every request opens its own connection and loads a fresh World, so a
`pull_rates` or a tune shows on the next click without a restart.

## `static/` - the board's look and behaviour

`board.js`, loaded last because it calls the other two, keeps one piece
of state - the map, the side, the bans, the red picks, the blue picks - in
`localStorage`, so a reload mid-game keeps the board. A click on a
portrait toggles that hero on that team (a banned hero cannot be picked; a
hero on one team cannot be on the other); a change debounces, then
fetches facts and inference together.

**The rosters.** One tile renderer draws the red roster, the blue roster
and the ban picker, so all three read as the same hero select: portrait
tiles in tank, damage and support columns, lit when picked, dotted when
on the other team, crossed out when banned, and dimmed once the
playbook's shape limits leave no legal six that seats one more of that
role - the board result carries the `(tanks, damage, supports)` triples
the hard limits allow, a click on a dimmed tile is refused with a note
rather than sent, and both teams are held to it, since a limit is the
game's form and not blue's alone. A hero the roster carries as
**announced** - one the wiki knows ahead of release, with its role,
subrole, health, kit and release day - sits in its role column as the same
tile, dimmed, tagged "coming soon", its portrait when the wiki has one and
a silhouette otherwise, with no click handler: it never enters the state,
is never sent as a pick, and the solver never fields it. Blizzard listing
the hero flips it to released and the tile comes alive on the next
refresh.

**The bans bar.** Collapsed by default: a header with the count and the
current bans as small portraits (click one to un-ban). Clicking the header
opens the picker - the five slots (two red, two blue, the lobby's) above
the same portrait grid the rosters use. A click on a tile bans that hero,
which leaves both rosters and the search; a click on a banned tile or on
its slot un-bans it; at five, the rest dim.

**The comps panel** answers at every stage of a draft. On top, the game
plan in prose: the ground, the side, what to play, what red's picks mean
and which of the six answer them, the family to stay in, and what it
rests on. Below, two seats. Blue's optimal counter to current picks
(left) is solved against red's revealed picks - or their likely starting
comp until they reveal one - and never against blue's own picks, so it
never collapses into what you hold. Red's most likely starting comp
(right) is a two-two-two filled slot by slot with the hero the map's pick
rates and the authored synergies make likeliest, past the bans; static
for the board, no strategy read. Neither seat carries a score: each is
its side's reference. Under a seat's cards sit the search's numbers
(candidates, seconds, the lean), the strategies satisfied - one bar per
strategy, headed by the count met, greyed where one did not apply - and
the alternatives.

**The scores** are the picks'. The badge above each picker is that seat's
comp as a share of its own optimal - blue's picks against blue's optimal,
red's against red's best counter to your picks (solved for that scale,
not shown); before any pick the badge shows the suggested six's 100. The
*fight odds* strip above the boxes is two bars stacked on one track,
blue's over red's: with both seats scored each bar is its side's share
over the two shares' sum, a split of 100, the share in the tooltip; with
one seat scored, its share alone; empty until a seat has a figure. Not a
fitted probability. When nothing can be a share of anything - the
playbook holds no heuristic, scored constraint or soft limit, or none
applies to this board yet - a seat reads *unscored*, one word, the
engine's reason in the badge's tooltip. Each box has a *clear*; *clear
all* in the header empties the map, the side, the bans and both teams,
and leaves the weights.

**The suggestions.** Blue's empty slots carry the fill - the best six that
keeps what you have locked, the optimal six before any pick - each a click
from locking; a tile shows the hero alone, its reasons in the tooltip and
on the comps tab.

**The facts panel** filters by text and by scope and says how many it
holds beside the filter - "464 facts", or "12 of 464 facts" under a
filter; the tab carries no number.

**The playbook panel** renders the catalog in three groups in the
equation's order, a row of anchors at the top, each group headed by its
count (an empty one says so), every card edged in its kind's colour, the
badge its kind alone, the meta line its form. Under each heuristic a
slider for its weight - 1 to 10 to the hundredth, a number box for the
exact figure, the file's weight as the inferred default, a reset. A
setting is kept in the browser, rides with every board request as
`weight=<id>:<value>`, is applied by the solver for that board only (each
result names the `weights` it was scored under) and never touches the
file until *store*: `POST /api/weight` `{id, weight}` becomes a `tune`
call - over HTTP at `COUNTER_MATRIX_MCP_URL` with the bearer token in the
compose stack, in-process on the local cluster - validated, logged with
its reason and mirrored; the file's weight is then the default and the
browser's setting is dropped. Only heuristics have a weight to set.

**The header** pins two pills top-right: *the math* and the repository on
GitHub (`COUNTER_MATRIX_REPO_URL` overrides the address). It keeps only
the short-lived flashes - a banned pick, a full team, a refused pick.
There is no footer: the facts panel says how many facts the board holds,
the rates' capture date is a fact, and a patch newer than the rates raises
the warning box under the header.

`board.css` is the game's look: dark navy surfaces on a faint diagonal
stripe, Bebas Neue for headings and labels, a gold accent for what
matters, red and blue for the two sides, blue, green and sand for
constraints, heuristics and assumptions - every colour a token in
`:root`. The rosters are laid out like a hero select: role columns and
portrait tiles.

## `facts/` - everything the database knows about a board

### `model.py` - the World

`load(cx)` reads every table into one object, once per request: the
heroes (role, subrole, health/shield/armor, the kit - weapons with their
firing configs, abilities, perks, every stat as a measurement with unit
and condition - keywords, the latest and previous rates, the per-map and
per-tier rates, counters both ways, best maps, playstyles), the maps
(mode, stages, playstyle fit), the meta snapshots and the patches newer
than the capture, synergies and partners, archetypes, the catalog's
shape. `Hero.finish()` derives what the kit implies - peak damage and
healing per second, burst, mobility and crowd-control tools, hitscan,
flight, anti-heal, cleanse, barrier, effective HP - so the metrics read
fields, not SQL. `resolve(map, red, blue, bans)` turns names into objects
through the same name matching the data layer uses, and refuses a banned
pick, an unknown hero, or a hero on both teams. A test in `tests/ui`
insists every data table is read here: a table nothing reads is not data.

### `compute.py` - the metrics registry

Pure functions over a World, and the one place a number is defined. The
board renders them as facts and the solver scores the same functions, so
a change here changes both. Four registries, each key with a one-line
meaning (`registry()` lists them all, and [inference.md](inference.md)
prints them as the vocabulary a strategy may reference):

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
expression reads. `expected_picks` is red's likely six from the data
alone. `TEAM_SIZE` (six, 6v6 Open Queue), `SIDED_MODES` (Escort, Hybrid),
`SIDES`, `is_sided` and `opposite` live here too.

### `engine.py` - the FactSet

`generate(world, map, red, blue, bans, side)` walks the board and numbers
what it finds. Facts are structured (scope, subject, key, value, unit,
source) so the inference layer reads them by key, and rendered as
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
team appear once a team has picks; matchup facts once both teams do. Ids
are dense and stable within a board, which is what makes a citation mean
something. Below the facts, numbered S1.., rides the playbook's record -
the archetypes, how many constraints, heuristics and assumptions the
catalog holds - citable but never mistaken for data, and not the
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
    Solver-->>Board: the game plan, the fight odds, blue's optimal with reasons and [F#]<br/>citations, red's likely starting comp, the suggestions for the empty slots
```

Sides exist on Escort and Hybrid maps only. The rates do not split by
side, so the side reaches the score only through a strategy whose `when`
reads `map.side` against the kit metrics (engage tools and anti-heal on
attack; deployables, barriers and reach on defense); the facts say which
side each team holds.

## What reads this package

The inference layer's solver (`compute`) and engine (`engine`, `model`),
the inference service, and the MCP tools `roster`, `facts`, `infer`,
`evaluate` and `board` - all through the same functions the board calls.
