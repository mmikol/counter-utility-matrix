# The board - `ui/`

The page over the three layers. Every click - a map, a side, a ban, a hero
on either roster - becomes a request that reads the database, and back
come every fact about that board (the facts layer's, in
[`facts/`](../facts/__init__.py)), the optimal six for both seats with the
current picks scored, and the playbook as it sits on disk. Once the map is
played, the record tab stores it as a recorded match. No layer imports the
board or its pages.

```bash
.venv/bin/python -m ui.board              # http://localhost:8017, the local cluster
COUNTRIX_INFERENCE_URL=http://localhost:8019 .venv/bin/python -m ui.board   # comps from the service
```

An `http.server` handler over psycopg, no web framework, no build step. In
the compose stack the `ui` container computes the facts itself and asks
the `inference` container for comps (`COUNTRIX_INFERENCE_URL`).

## `board.py` and `pages.py` - the page and its endpoints

`pages.py` renders the page, a shell over the static files that injects
only `TEAM` (six), `BANS` (five) and whether the board writes, and the
record panel's frame: the result buttons `record_match` takes, disabled
with a note on how to turn recording on while the board writes nothing. `board.py`
serves it and the JSON endpoints behind the host guard `db/web.py` puts on
all three servers, and a call it relays answers by that module's status
map ([security.md](security.md)).

| route | serves |
| --- | --- |
| `/` | the board: the map selector, the attack/defense switch (Escort and Hybrid maps), the bans bar, the red and blue rosters grouped by role, and four panels - **comps**, **facts**, **playbook**, **record** |
| `/static/<file>` | `board.css`, `board.js`, `comps.js`, `playbook.js`, `record.js` and `bebas-neue.woff2`, nothing else |
| `/api/roster` | the roster `facts/roster.py` builds, which the door's `roster` tool lists too: every hero (role, subrole, health pool, portrait, status, release day) and every map (mode, top style, sided or not), with the role icons and the patches newer than the rates |
| `/api/facts?map=&side=&red=&blue=&bans=` | the FactSet for the board as JSON: the facts, their count and the playbook's record |
| `/api/board?map=&side=&red=&blue=&bans=[&weights=&client=&pool=]` | the board solved at any stage under the playbook tab's weights: the `board` tool's answer ([mcp.md](mcp.md#the-tools)) without the countered case, which the page never reads. `serve.handle_board` in-process, or the service's `/board` when `COUNTRIX_INFERENCE_URL` is set, the query forwarded as received before any connection opens |
| `/api/strategies` | the catalog: every constraint, heuristic and assumption with its kind, form, frontmatter and body - `serve.handle_strategies` in-process, or the service's `/strategies` |
| `/math` | `static/math.html` in the page shell, the constants it quotes (`SYNERGY_PULL`, `REFERENCE_SIZE`, `NEED_BUDGET` and the search's four) filled in by `pages.py`: the equation, the scoring function, the board and how the layers fit |
| `/tests` | `static/tests.html` in the page shell: the designed proof, the adversarial hunt, the random sample, the regression gate, the suite, and what none of it proves |
| `POST /api/weight` `{id, weight}` | the board's first write, a `tune` call through the door: over HTTP to `COUNTRIX_MCP_URL` with the bearer token when that is set (the compose stack), in-process otherwise. Off by default; `COUNTRIX_READ_ONLY=0` turns it and the *store* button on |
| `POST /api/match` `{map, side, result, blue, red, bans, played_on, note}` | the board's second write, a `record_match` call by the same path as the weight's: the board as a played map, blue's result from the record panel ([mcp.md](mcp.md#the-recorded-matches)). Any other key is dropped. Off with the weight; `COUNTRIX_READ_ONLY=0` turns it and the result buttons on |

Both POSTs answer in the order `board.py` checks: 415 for a body that does
not claim `application/json`, with writes off too; 403 while the board is
read-only - a weight applies to the session only, and a match is recorded
once the board runs with `COUNTRIX_READ_ONLY=0` or through `/record`; 400
for a body past 4 KB (a weight) or 16 KB (a match) or not JSON, for an id
that is not one or a weight that is not a number, and for the tool's
refusal - a weight outside 0..10, no such strategy, a team short of six,
three tanks, a banned hero picked, a side missing on a sided map; the
door's 429 as it came; 502 for a door that fails or does not answer, and
500 for a crash in-process.

`/api/roster`, `/api/facts` and an in-process `/api/board` each open their
own connection and load a fresh World, so a `pull_rates` or a tune shows
on the next click without a restart. A board forwarded to the service
opens none, so it answers while the database is out of reach.

## `static/` - the board's look and behaviour

```
static/
  board.css      the look: the game's - dark surfaces, Bebas Neue headings, a gold accent, red and blue for the sides
  bebas-neue.woff2  the display face, Bebas Neue Regular, served from the board itself
  OFL.txt        its licence, the SIL Open Font License 1.1, which travels with the font
  board.js       state, the rosters, the picks, the bans, the fetches, boot
  comps.js       the comps tab: a seat's result and the two seats
  playbook.js    the playbook tab: the groups, the cards, the weight sliders
  record.js      the record tab: the board as a played map, and its POST
  math.html      the math page's article
  tests.html     the tests page's article
```

`board.js` loads last, since it calls the other three. It keeps the map, the
side, the bans, both teams' picks and the slider weights in
`localStorage`, so a reload mid-game keeps the board. A click on a
portrait toggles that hero on that team: a banned hero cannot be picked,
and a hero may play for both teams, never twice on one. A change
debounces, then fetches facts and the board together. Each board request
names the page (`client`), so the server stops a board the page has moved
past - that one answers 400 - and the page aborts the older request. A
request that fails says so where its answer would have gone, keeps nothing
of the last board, and is tried again when the page comes back into view
or the network returns. A roster that fails to load is said in the warning
box and asked for again, the wait doubling up to half a minute; nothing
else is drawn before it.

**The rosters.** One tile renderer draws both rosters and the ban picker
as the same hero select: portrait tiles in tank, damage and support
columns, lit when picked, dotted when on the other team, crossed out when
banned. A tile dims once the queue's two-tank limit or the playbook's
shape limits - the `(tanks, damage, supports)` triples the board result
carries - leave no legal six that seats one more of its role, and a click
on it is refused with a note. The limits hold both teams: they are the
game's form, not blue's alone. An **announced** hero, one the wiki knows
ahead of release, sits in its role column as the same tile, dimmed and
tagged "coming soon", with its portrait or a silhouette. It has no click
handler, so it never enters the state, and the solver never fields it;
once Blizzard lists the hero, the tile comes alive on the next refresh.

**The bans bar** starts collapsed: the count and the current bans as small
portraits, a click on one un-bans it. Opened, it shows the five slots (two
red, two blue, the lobby's) over the rosters' portrait grid. A click on a
tile bans that hero, which leaves both rosters and the search; a click on
a banned tile or its slot un-bans it; at five, the rest dim.

**The comps panel** answers at every stage of a draft: the game plan in
prose on top, then two seats, neither with a score. Blue's (left) shows
the six the plan describes - *your picks, the rest filled* from one to
five picks, *your six* at six - over blue's *optimal vs red's picks* (*vs
red's likely six* before red reveals one, alone before any pick), which
blue's own picks never constrain. Red's (right) is their most likely
starting comp, a two-two-two filled slot by slot from the map's pick rates
and the wiki's synergies, past the bans; it reads no strategy, and only a
new map, side or ban sends it back to *searching*. Under a six's cards sit
the search's numbers (candidates, seconds, the lean), the strategies in
three tabs - *satisfied*, *costing* with the summed cost, *did not read* -
under a filter, each bar's tooltip saying why it paid or did not, and last
the alternatives.

**The badges** above the pickers are each seat's comp as a share of its
own optimal: blue's picks against blue's optimal, red's against red's best
counter to your picks (solved for that scale, not shown). A seat still
drafting reads the share the best six from its picks reaches, in the badge
and the strip alike, and the tooltip says so; before any pick the badge
shows the suggested six's 100. The engine words each badge
(`momentum.badges`, a label and a tip); the page only shows it.

**The fight odds** strip is two bars stacked on one track, blue's over
red's. With both seats scored, each bar is its side's share over the two
shares' sum, a split of 100, the share in the tooltip; with one seat
scored, its share alone; with neither, the engine's verdict sits under
them. Not a fitted probability. When the playbook holds no heuristic,
scored constraint or soft limit, or none applies to this board yet, a seat
reads *unscored*, picks or not, the engine's reason in the tooltips.

**The suggestions.** Blue's empty slots carry the fill - the best six that
keeps your locked picks, the optimal six before any pick - each a click
from locking, its reasons in the tooltip and on the comps tab. A filled
slot's tooltip is the reason this board gives its hero: blue's from the
fill or the six, red's from their current comp.

**The facts panel** filters by text and by scope and says how many it
holds beside the filter ("12 of 464 facts" under a filter); the tab
carries no number.

**The playbook panel** lists the catalog in three groups in the equation's
order, under a row of anchors, each card edged in its kind's colour and
its meta line its form. Under each heuristic sits a slider for its weight,
0 to 10 to the hundredth, with a number box, a reset and the file's weight
as the default. A setting stays in the browser and rides with every board
request as `weights=<id>:<value>`; the solver applies it to that board
only (each result names its `weights`), and the file is untouched. A
setting whose heuristic the catalog no longer holds is dropped when the
playbook loads. With writes on, *store* sends the weight to
`POST /api/weight`; the file's weight becomes the default, and the
browser's setting is dropped.

**The record panel** is the board as a played map: the map and blue's
side, blue's six, red's six and the bans, as the rosters and the bans bar
hold them, over the day it was played (the browser's today unless
changed), a note and three buttons - win, loss, draw, blue's result, blue
always the owner's team. A six is the six on the field longest, so the
rosters are set to what was played before a result is pressed. The panel
names what the board still lacks - the map, a side on a sided map, a team
short of six - and holds the buttons until it has them; every other rule
is `record_match`'s, whose refusal comes back as a flash. A result sends
`POST /api/match`, and the panel says what the door recorded; the buttons
stay off for that board until it changes, so one map is recorded once. A
board that writes nothing renders the buttons disabled and says how to
turn recording on - `COUNTRIX_READ_ONLY=0`, or the `/record` skill in a
Claude Code session.

**The header** pins three pills top-right: *the math*, *the tests* and the
repository on GitHub (`COUNTRIX_REPO_URL` overrides the address). Its
*clear all* empties the map, the side, the bans and both teams and leaves
the weights; each team's box has its own *clear*. Its only messages are
short-lived flashes - a banned pick, a full team, a refused pick. A patch
newer than the rates raises the warning box; the rates' capture date is a
fact.

`board.css` puts the game's look on a faint diagonal stripe and colours
the kinds: blue for constraints, green for heuristics, sand for
assumptions. The core palette is tokens in `:root`; the rest, the sand
`#d9b36a` among them, are literals. The code, the styles and the font are
served from `static/`, Impact standing in until the font arrives; the
portraits and role icons load as `<img>` from Blizzard's CDNs.

## `validation.py` and `charts.py` - the validation report

```bash
.venv/bin/python -m ui.validation                                  # the playbook in force
.venv/bin/python -m ui.validation --playbook tests/fixtures/playbook --all --effect 0.55
```

The playbook judged against the recorded matches
([inference.md](inference.md#how-the-playbook-is-judged)): the text the
`validate_playbook` tool answers goes to stdout, and a page of charts and
its JSON to `db/raw/validation.html` (`--out` moves them). The page loads
nothing: its styles, its tooltip script and every chart, inline SVG, are
in the file. It draws the decided maps against the maps an effect needs,
each model's log loss against the coin flip's with its interval, each
family's ablation, M4's calibration, the playbook score difference by
result and the hero effects, each with a table of the same numbers, then
the digests and every judged map. Light and dark follow the system. The
page carries rate-derived figures and is never published; `db/raw` is
gitignored. A refusal - a folder outside the repo, an effect that is not
a win chance - exits with status 2.

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
    Facts->>DB: load the World (27 queries)
    Facts-->>Board: F1..Fn - every fact about those heroes,<br/>the map, each team, the matchup
    Board->>Solver: /api/board (map, side, red, blue, bans)
    Solver->>Solver: blue's seat: shapes the limits allow · per-role pools ·<br/>every candidate scored · local search
    Solver->>Solver: red's seat, the other side: their best counter to your picks
    Solver->>Solver: both current comps: six locked -> ranked against the field;<br/>fewer -> scored with the optimal search's bounds
    Solver->>Facts: the FactSet for each (map, side, red, the six)
    Solver-->>Board: the game plan, the fight odds, blue's optimal with reasons and [F#]<br/>citations, red's likely starting comp, the suggestions for the empty slots
```

Sides exist on Escort and Hybrid maps only, and the facts say which side
each team holds. The rates do not split by side, so a strategy brings the
side in through a `when` that reads `map.side`. The shipped playbook holds
none, so today the side reaches no score; the two in the [fixture
playbook](../tests/fixtures/playbook/) show the form - engage tools and
anti-heal on attack, deployables, barriers and reach on defense.
