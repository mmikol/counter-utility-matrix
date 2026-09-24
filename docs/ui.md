# The board - `ui/`

The page over the three layers. Every click - a map, a side, a ban, a
hero on either roster - becomes a request; the database is read; back
come every fact about that board (the facts layer's,
[facts.md](facts.md)), the optimal six for both seats with the current
picks scored, and the playbook as it sits on disk. The board reads: its
one write, a heuristic's weight stored from its slider, is off by default
(`COUNTRIX_READ_ONLY`) and, when turned on, is a `tune` call through the
door. No layer imports the board or its pages.

```bash
.venv/bin/python -m ui.board              # http://localhost:8017, the local cluster
COUNTRIX_INFERENCE_URL=http://localhost:8019 .venv/bin/python -m ui.board   # comps from the service
```

An `http.server` handler over psycopg, no web framework, no build step -
the footprint `ui/board.py`'s docstring states. In the compose stack the
`ui` container runs the same module with `COUNTRIX_INFERENCE_URL` pointing
at the `inference` container, so the board computes facts in-process and
asks the service for comps.

## Layout

```
ui/
  __init__.py      the package's map
  board.py         the server: the settings, the JSON endpoints, the handler that routes to them
  pages.py         the page shell, the math and tests pages, the static files they load
  static/
    board.css      the look: the game's - dark surfaces, Bebas Neue headings, a gold accent, red and blue for the sides
    bebas-neue.woff2  the display face, Bebas Neue Regular, served from the board itself
    OFL.txt        its licence, the SIL Open Font License 1.1, which travels with the font
    board.js       state, the rosters, the picks, the bans, the fetches, boot
    comps.js       the comps tab: a seat's result and the two seats
    playbook.js    the playbook tab: the groups, the cards, the weight sliders
    math.html      the math page's article
    tests.html     the tests page's article
```

## `board.py` and `pages.py` - the page and its endpoints

`pages.py` renders the page, and `board.py` serves it and answers the JSON
endpoints. The page is a shell: the stylesheet, the scripts and the font are
static files, and `TEAM` (six), `BANS` (five) and whether the board writes
are the only values the page injects, so the scripts have no constant to
keep in step with the Python.

Every route stands behind the guard `db/web.py` puts on all three servers:
a request whose `Host` or `Origin` names neither a local name nor one the
board was started with (`--allow-host`, the public name of a published
board) answers 403 before it is routed - a page rebound to the board's
address sends its reads under its own host name. Each board solved and
each request that fails leaves one line on stderr, the container's log:
the request line, the status and the seconds; the page and its files are
quiet, and a service that does not answer is named there with the
reason.

| route | serves |
| --- | --- |
| `/` | the board: map selector, attack/defense switch (Escort and Hybrid maps), the bans bar, the red and blue rosters grouped by role with the announced hero at the end, and three panels - **comps**, **facts**, **playbook** |
| `/static/<file>` | `board.css`, `board.js`, `comps.js`, `playbook.js`, `bebas-neue.woff2` - stylesheets, scripts and the display font, nothing else |
| `/api/roster` | every hero (role, subrole, portrait, status, release day), every map (mode, top style, sided or not), the role icons, and the patches newer than the rates |
| `/api/facts?map=&side=&red=&blue=&bans=` | the FactSet for the board, as JSON: the facts, their count, and the playbook's record |
| `/api/board?map=&side=&red=&blue=&bans=[&weights=&client=]` | the board solved at any stage - the inference layer's `board()` in-process, or the service's `/board` when `COUNTRIX_INFERENCE_URL` is set, forwarded before any connection opens: blue's optimal (the counter to red's selection), red's optimal (their counter to yours), both current comps on those scales, the empty blue slots filled, red's likely starting comp, the fight odds, the game plan and the shapes the limits allow, under the playbook tab's weights. The page reads no countered case, so none is solved; a newer board from the same `client` (one lane when none is named) supersedes one still solving, which answers 400 |
| `/api/strategies` | the strategies catalog: every constraint, heuristic and assumption with its kind, form, frontmatter and body |
| `/math` | `static/math.html` in the page shell: the equation, the scoring function (what 100 means, fight odds, the argmax), the board (red's likely starting comp and its formula, blue's optimal counter, the weights) and how the layers fit, with a table of contents; linked from the board's header |
| `/tests` | `static/tests.html` in the page shell: what the engine is checked against - the designed proof over every legal six, the adversarial hunt against a wider search, the random sample and the rate it bounds, the regression gate, the properties the suite holds, and what none of it proves |
| `POST /api/weight` `{id, weight}` | the board's one write, a `tune` call - off by default (403): a weight applies to the session only; `COUNTRIX_READ_ONLY=0` turns it and the *store* button on. A body that does not claim `application/json` is refused with 415, and one past 4 KB with 400 |

`/api/roster`, `/api/facts` and an in-process `/api/board` each open their
own connection and load a fresh World, so a `pull_rates` or a tune shows on
the next click without a restart. A board forwarded to the service opens
none, so it answers while the database is out of reach.

## `static/` - the board's look and behaviour

`board.js`, loaded last because it calls the other two, keeps one piece
of state - the map, the side, the bans, the red picks, the blue picks -
in `localStorage`, so a reload mid-game keeps the board. A click on a
portrait toggles that hero on that team (a banned hero cannot be picked;
a hero on one team cannot be on the other); a change debounces, then
fetches facts and the board together. A board request names the page
(`client`, drawn once per page load), so the server stops a board the
page has moved past, and the page aborts the older request. A request that
fails says so where its answer would have gone - the facts tab, the blue
seat, the strip - blanks the badges and the plan, keeps nothing of the
last board, and is tried again when the page comes back into view or
the network returns. A roster that fails to load is said in the warning
box and asked for again, waiting twice as long each time up to half a
minute; nothing else is drawn before it.

**The rosters.** One tile renderer draws the red roster, the blue roster
and the ban picker, so all three read as the same hero select: portrait
tiles in tank, damage and support columns, lit when picked, dotted when
on the other team, crossed out when banned, and dimmed once the queue's
two-tank limit or the playbook's shape limits leave no legal six that
seats one more of that role - the board result carries the `(tanks,
damage, supports)` triples they allow, a click on a dimmed tile is
refused with a note rather than sent, and both teams are held to it,
since a limit is the game's form and not blue's alone. A hero the roster carries as
**announced** - one the wiki knows ahead of release, with its role,
subrole, health, kit and release day - sits in its role column as the
same tile, dimmed, tagged "coming soon", its portrait when the wiki has
one and a silhouette otherwise, with no click handler: it never enters
the state, is never sent as a pick, and the solver never fields it.
Blizzard listing the hero flips it to released and the tile comes alive
on the next refresh.

**The bans bar.** Collapsed by default: a header with the count and the
current bans as small portraits (click one to un-ban). Clicking the
header opens the picker - the five slots (two red, two blue, the lobby's)
above the same portrait grid the rosters use. A click on a tile bans that
hero, which leaves both rosters and the search; a click on a banned tile
or on its slot un-bans it; at five, the rest dim.

**The comps panel** answers at every stage of a draft. On top, the game
plan in prose: the ground, the side, what to play, what red's picks mean
and which of the six answer them, the family to stay in, and what it
rests on. Below, two seats. Blue's (left) shows the six the plan
describes: from one to five picks, *your picks, the rest filled*; at six,
*your six*; and below it blue's *optimal vs red's picks* (*vs red's likely
six* before red reveals one), which blue's own picks never constrain -
before any blue pick, the optimal alone. Red's most likely starting comp
(right) is a two-two-two filled slot by slot with the hero the map's pick
rates and the wiki's synergies make likeliest, past the bans; static for
the board, no strategy read, and only a new map, side or ban sends it back
to *searching*. Neither seat carries a score. Under
a six's cards sit the search's numbers (candidates, seconds, the lean),
the strategies satisfied - one bar per strategy, headed by the count met,
greyed where one did not apply - and the alternatives.

**The scores** are the picks'. The badge above each picker is that seat's
comp as a share of its own optimal - blue's picks against blue's optimal,
red's against red's best counter to your picks (solved for that scale,
not shown); a seat still drafting reads the share the best six from its
picks reaches, as the strip reads it, and says so in the tooltip; before
any pick the badge shows the suggested six's 100. The engine words each
badge (`momentum.badges`, a label and a tip) and the page only shows
them. The *fight odds* strip
above the boxes is two bars stacked on one track, blue's over red's: with
both seats scored each bar is its side's share - a side still drafting
read through its fill, on both sides alike - over the two shares' sum, a
split of 100, the share in the tooltip; with one seat scored, its share
alone; while neither bar has a figure, the engine's verdict sits under
them. Not a fitted probability. When nothing can be a share of anything -
the playbook holds no heuristic, scored constraint or soft limit, or none
applies to this board yet - a seat reads *unscored*, one word, picks or
not, the engine's reason in the badge's and the bar's tooltip. Each box
has a *clear*; *clear all* in the header empties the map, the side, the
bans and both teams, and leaves the weights.

**The suggestions.** Blue's empty slots carry the fill - the best six
that keeps what you have locked, the optimal six before any pick - each a
click from locking; a tile shows the hero alone, its reasons in the
tooltip and on the comps tab. A filled slot's tooltip is the reason this
board gives its hero - blue's from the fill or the six, red's from their
current comp.

**The facts panel** filters by text and by scope and says how many it
holds beside the filter ("12 of 464 facts" under a filter); the tab
carries no number.

**The playbook panel** renders the catalog in three groups in the
equation's order, a row of anchors at the top, each group headed by its
count (an empty one says so), every card edged in its kind's colour, the
badge its kind alone, the meta line its form - a heuristic's: direction,
metric, weight, *need* where it is one, its `when`. Under each heuristic a
slider for its weight - 0 to 10 to the hundredth, a number box for the
exact figure, the file's weight as the inferred default, a reset. A
setting is kept in the browser, rides with every board request as
`weights=<id>:<value>`, is applied by the solver for that board only (each
result names the `weights` it was scored under) and never touches the
file. A setting whose heuristic the catalog no longer holds has no row to
clear it from, so it is dropped when the playbook loads. By default that is the whole story: the board is read-only, there
is no *store* button and `POST /api/weight` answers 403. With
`COUNTRIX_READ_ONLY=0` the button returns, and *store* -
`POST /api/weight` `{id, weight}` - becomes a `tune` call: over HTTP at
`COUNTRIX_MCP_URL` with the bearer token in the compose stack,
in-process on the local cluster - validated, logged with its reason and
mirrored; the file's weight is then the default and the browser's
setting is dropped. Only heuristics have a weight to set.

**The header** pins two pills top-right: *the math* and the repository on
GitHub (`COUNTRIX_REPO_URL` overrides the address). It keeps only
the short-lived flashes - a banned pick, a full team, a refused pick.
There is no footer: the facts panel says how many facts the board holds,
the rates' capture date is a fact, and a patch newer than the rates
raises the warning box under the header.

`board.css` is the game's look: dark navy surfaces on a faint diagonal
stripe, Bebas Neue for headings and labels, a gold accent for what
matters, red and blue for the two sides, blue, green and sand for
constraints, heuristics and assumptions - every colour a token in
`:root`. The rosters are laid out like a hero select: role columns and
portrait tiles. The face is served from `static/` with its licence, so
the page loads nothing from another host; Impact stands in until it
arrives.

## One click on the board

```mermaid
sequenceDiagram
    actor You
    participant Board as ui/board.py
    participant Facts as facts/ (World + FactSet)
    participant Solver as inference/ (solver)
    participant DB as PostgreSQL

    You->>Board: pick the map and your side, set the bans,<br/>click red picks as they reveal, lock your blue picks
    Board->>Facts: /api/facts (map, side, red, blue, bans)
    Facts->>DB: load the World (a dozen queries)
    Facts-->>Board: F1..Fn - every fact about those heroes,<br/>the map, each team, the matchup
    Board->>Solver: /api/board (map, side, red, blue, bans)
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
