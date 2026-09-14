"""The UI LAYER's board: a map selector and a red and a blue roster,
organised and styled like the game's hero select, over the facts engine
and the inference layer.

    python -m ui.board            # serves http://localhost:8017

Standard library only. Every click re-reads the database: the facts
panel is the FactSet for (map, red, blue), the comps panel is the
inference layer's absolute optimal for blue, red's optimal around its
revealed picks, and the current blue picks scored against blue's optimal,
and the playbook panel is the strategies
catalog as it sits on disk. JSON endpoints under /api/ serve the same
three things.
"""

import html
import json
import os
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import psycopg

from db import psql
from inference import catalog as catalog_module
from inference import engine as inference_engine
from ui.facts import engine as facts_engine
from ui.facts import model
from ui.facts.compute import SIDED_MODES, TEAM_SIZE

PORT = int(os.environ.get("COUNTER_MATRIX_UI_PORT", "8017"))

# The inference layer runs in-process unless a service is named: in the
# compose stack the `inference` container serves it (inference/serve.py).
INFERENCE_URL = os.environ.get("INFERENCE_URL", "").rstrip("/")
# The repository the header links to; override when the repo moves.
REPO_URL = os.environ.get("COUNTER_MATRIX_REPO_URL", "https://github.com/mmikol/counter-utility-matrix")
GITHUB_MARK = ("<svg viewBox='0 0 16 16' width='15' height='15' aria-hidden='true'><path fill='currentColor' d='M8 0C3.58 0 0 3.58 0 8"  # noqa: E501
               "c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94"  # noqa: E501
               "-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2"  # noqa: E501
               "-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0"  # noqa: E501
               " 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95"  # noqa: E501
               ".29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z'/></svg>")  # noqa: E501


def dsn():
    return psql.default_dsn()


def remote(path, query=None, payload=None):
    """Forward to the inference service -> (json, status)."""
    url = INFERENCE_URL + path
    if query:
        url += "?" + urlencode(query, doseq=True)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read().decode("utf-8")), error.code
        except ValueError:
            return {"error": "inference service returned %d" % error.code}, error.code
    except (urllib.error.URLError, OSError) as error:
        return {"error": "inference service unreachable: %s" % error}, 502


def esc(x):
    return html.escape(str(x if x is not None else ""))


# --- JSON endpoints ---------------------------------------------------------

def _board(query):
    map_name = (query.get("map") or [None])[0] or None
    red = [x for x in query.get("red", []) if x]
    blue = [x for x in query.get("blue", []) if x]
    bans = [x for x in query.get("ban", []) if x][:5]
    side = (query.get("side") or [""])[0]
    return map_name, red, blue, bans, side


def api_roster(cx):
    world = model.load(cx)
    heroes = [{"name": h.name, "slug": h.slug, "role": h.role, "subrole": h.subrole,
               "pool": h.pool, "portrait": h.portrait, "status": h.status,
               "release_date": str(h.release_date) if h.release_date else None,
               "subrole_icon": (world.subrole_passives.get(h.subrole) or (None, None, None))[2]}
              for h in world.heroes_by_role()]
    maps = [{"name": m.name, "mode": m.mode, "style": m.style_top,
             "sided": (m.mode or "") in SIDED_MODES}
            for m in world.maps_sorted()]
    return {"heroes": heroes, "maps": maps, "role_icons": world.role_icons,
            "snapshots": world.snapshots, "newer_patches": world.newer_patches}


def api_facts(cx, query):
    map_name, red, blue, bans, side = _board(query)
    world = model.load(cx)
    try:
        fs = facts_engine.generate(world, map_name, red, blue, bans, side)
    except ValueError as error:
        return {"error": str(error)}, 400
    return fs.to_dict(), 200


def api_infer(cx, query):
    """Both seats' optimal six and the current comp - the two displays."""
    map_name, red, blue, bans, side = _board(query)
    if INFERENCE_URL:
        return remote("/board", {"map": map_name or "", "side": side, "red": red,
                                 "blue": blue, "ban": bans})
    world = model.load(cx)
    try:
        b = inference_engine.board(world, map_name, red, blue, bans, side)
    except ValueError as error:
        return {"error": str(error)}, 400
    return inference_engine.board_dict(b), 200


def api_strategies():
    if INFERENCE_URL:
        return remote("/strategies")[0]
    catalog = catalog_module.load()
    return {"strategies": [h.to_dict() for h in catalog]}


# --- the board page ---------------------------------------------------------
#
# The page is a shell: the stylesheet and the script are static files under
# ui/static/ (editable and lintable on their own), served by this same
# handler; TEAM and BANS come from the page so the script has no constant
# to keep in step.

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_TYPES = {".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8"}


def static_file(name):
    """(bytes, content type) for a file under ui/static, or None."""
    ext = os.path.splitext(name)[1]
    if "/" in name or ".." in name or ext not in STATIC_TYPES:
        return None
    path = os.path.join(STATIC_DIR, name)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as handle:
        return handle.read(), STATIC_TYPES[ext]


HEAD = ("<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<link rel='stylesheet' href='/static/board.css'>")




def view_board():
    return (HEAD + "<title>Counter Utility Matrix</title><main>"
            "<header class='top'><h1>Counter <span>Utility Matrix</span></h1>"
            "<div class='mapsel'><select id='mapsel'></select><span class='mode' id='mode'></span>"
            "<span class='sideseg' id='sideseg' title='blue"
            " attacks or defends; red gets the other side'>"
            "<button data-side='attack'>attack</button><button data-side='defense'>defense</button>"
            "</span>"
            "<button id='clearall' title='the map, the side, the bans and both teams'>"
            "clear all</button>"
            "<span class='flash' id='flash'></span></div>"
            "<span class='links'><a class='mathlink' href='/math' title='the"
            " equation and how the pieces fit'>the math</a>"
            "<a class='gh' href='%s' target='_blank' rel='noopener'"
            " title='the repository on GitHub'>%s GitHub</a>"
            "</span>"
            "</header>"
            "<div class='bans' id='bans'><div class='banhead' id='banhead'"
            " title='open or close the ban picker'>"
            "<h3>bans</h3><span class='bancount' id='bancount'>"
            "</span><span class='banmini' id='banmini'></span>"
            "<span class='hint'>up to five, all optional: each team's two and the lobby's -"
            " a banned hero leaves both rosters and the search</span>"
            "<span class='caret'>&#9656;</span></div>"
            "<div class='banbody' id='banbody'><div class='slots' id='banslots'></div>"
            "<div class='roles' id='banroster'></div></div></div>"
            "<div class='warnbox' id='vintage' style='display:none'></div>"
            "<div class='momentum' id='momentum'></div>"
            "<div class='teams'>"
            "<section class='team blue'><h2>blue team <span class='tscore' id='bluescore'"
            " title=\"your picks so far, as a share of blue's optimal\">"
            "</span>"
            "<small>your locked picks - the inference layer fills the rest</small>"
            "<small style='margin-left:auto' id='bluecount'></small>"
            "<button class='clearteam' data-clear='blue' title='clear every blue pick'>"
            "clear</button>"
            "</h2>"
            "<div class='slots' id='blueslots'></div><div class='roles' id='blueroster'>"
            "</div></section>"
            "<section class='team red'><h2>red team <span class='tscore' id='redscore'"
            " title=\"their picks so far, as a share of their best counter to yours\">"
            "</span>"
            "<small>the enemy - click their heroes as they reveal</small>"
            "<small style='margin-left:auto' id='redcount'></small>"
            "<button class='clearteam' data-clear='red' title='clear every red pick'>clear</button>"
            "</h2>"
            "<div class='slots' id='redslots'></div><div class='roles' id='redroster'>"
            "</div></section>"
            "</div>"
            "<nav class='tabs'><button data-tab='comps'>comps</button>"
            "<button data-tab='facts'>facts <span id='factsn'></span></button>"
            "<button data-tab='playbook'>playbook</button></nav>"
            "<section class='panel' id='tab-comps'><div class='plan' id='plan'>"
            "</div><div class='seats'>"
            "<div class='seat blue' id='inf-blue'></div><div class='seat red' id='inf-red'>"
            "</div></div></section>"
            "<section class='panel' id='tab-facts'><div class='tools'>"
            "<input type='text' id='filter' placeholder='filter"
            " facts - try a hero, CAUTION, derived:, team.'>"
            "<span id='chips'></span></div>"
            "<table class='facts'><tbody id='factbody'></tbody></table>"
            "<p class='legend'>every line is a row or a formula"
            " over the database, numbered for citation;"
            " the /comp skill and the inference layer read exactly these.</p></section>"
            "<section class='panel' id='tab-playbook'><div id='playbook'></div></section>"
            "<footer class='foot'><span id='status'></span><span id='captured'></span></footer>"
            "</main><script>var TEAM = %d, BANS = 5;</script>"
            "<script src='/static/board.js'></script>" % (REPO_URL, GITHUB_MARK, TEAM_SIZE))


# --- the math page -------------------------------------------------------------

def _page(title, body):
    return (HEAD + "<title>%s</title>"
            "<main><header class='top'><h1><a href='/'>Counter <span>Utility Matrix</span></a></h1>"
            "<span class='sub'>%s</span></header>%s</main>" % (esc(title), esc(title), body))


MATH = """
<article class='math'>
<h2>The equation</h2>
<pre class='eq'>DATA           = HEROES &cup; MAPS &cup; META              the tables, as set
for each domain D in { HEROES, MAPS, META }:
  INDEPENDENT(D) = &#8899; facts(s)      over each selection s in D    s alone: its own row
  DEPENDENT(D)   = &#8899; facts(s &#8904; t)  over the other selections t   s joined with t
  FACTS(D)       = INDEPENDENT(D) &cup; DEPENDENT(D)
FACTS          = FACTS(HEROES) &cup; FACTS(MAPS) &cup; FACTS(META)
FACTS(D) &cap; FACTS(E) = the joins of D with E: what only their intersection can say
STRATEGIES     = CONSTRAINTS &cup; HEURISTICS &cup; ASSUMPTIONS   the playbook: markdown files
COMP           = ARGMAX[ STRATEGIES( FACTS ) ]            the solver searches, the agent argues
</pre>
<p><b>DATA</b> is the authoritative data, and only that: what is pulled from the sources and set
in the database. <b>HEROES</b> are the kits - roles, subroles, health pools, every ability with its
published numbers, who counters whom, which pairs work together. <b>MAPS</b> are the pool - the
mode, the stages, whether a map has sides, and the authored note on what kind of fight it
rewards. <b>META</b> is the record - win, pick and ban rates per hero, per map, per rank, captured
as dated snapshots, plus the patches that shipped since.</p>
<p><b>FACTS</b> is what the fact engine derives from that data for one board - a map, a side,
red's picks, yours, the bans - and every domain yields two kinds. The <b>independent</b> facts of
a domain are each selection alone, read from its own row, and no other selection changes them: a
hero's role, pool, range, every ability's numbers, its overall rates and its style; the map's
mode, stages, sides and the note on what it rewards; the meta's vintage, source and queue. The
<b>dependent</b> facts are the selection joined with others - &#8904;, the rows of two tables that
meet on a key, which is what intersecting two selections means in a database - and a join belongs
to every domain it touches, so the dependent facts are where the domains' fact sets intersect: a
hero's rate on this map and its delta against its baseline (HEROES &cap; MAPS &cap; META: heroes
&#8904; map_meta &#8904; maps), who among red's picks it answers and who answers it (HEROES &cap;
HEROES: heroes &#8904; counters &#8904; heroes), who among your picks it pairs with (&#8904;
synergies), the map's leaders and strugglers and how your picks fit its style (MAPS &cap; HEROES
&cap; META), the team as one thing (the six joined and aggregated), the matchup (the twelve,
compared), and the bans (a banned hero joined with both teams' counters). The tables themselves
share no rows - DATA is their union - and every intersection is a join. Every selection you add
opens new joins, and the engine derives every fact they support: a board with nothing on it has
only the meta's facts, a full board about a thousand. The facts are numbered F1, F2, ... and every
claim the board makes cites them; the numbers a strategy reads are the dependent facts.</p>
<p><b>STRATEGIES</b> is the playbook: markdown files, one per strategy, in three kinds.
A <b>constraint</b> is a limit the comp may not cross (at most two tanks), a scored adjustment
(a bonus or a penalty when a condition holds), or a ground rule in prose. A <b>heuristic</b> is a
metric to push in a direction with a weight: effective HP up, exposure down, cohesion up.
An <b>assumption</b> is prose by definition - what the model takes as given (players play
optimally; rates are Role Queue on console) - shown with every result and never scored. A
strategy is written as a name, a kind and a paragraph; the formula, the metric and the weight
are inferred from that and stored in the same file.</p>
<p><b>COMP</b> is the argmax: of every legal six under the constraints, the one the function
below scores highest on the facts of this board. Nothing in this is sampled or guessed: the same
board gives the same six every time, in a second or two.</p>
<h2>The function: STRATEGIES( FACTS )</h2>
<p>A scoring function. It takes one candidate six for blue on one board and returns one number;
ARGMAX searches the candidate sixes for the highest. What it reads is not the numbered sentences
but the same dependent variables in structured form, the <b>namespace</b>: <code>team</code> (the
aggregates over the candidate six, computed against red), <code>enemy</code> (red's aggregates,
fixed for the board), <code>matchup</code> (the two compared), <code>map</code> and
<code>world</code>. They come from the same functions the fact engine uses, so a strategy's
<code>team.antiheal</code> is the number the facts tab prints. For every candidate the solver
rebuilds <code>team</code> and <code>matchup</code>; the other three never change during a
search.</p>
<p>Each kind of strategy contributes one kind of term. A <b>limit</b> (a constraint with
<code>require</code>) is a boolean over the namespace: a hard limit that fails removes the six
from the search; a soft one that fails subtracts its penalty. A <b>heuristic</b> reads its metric,
normalises it to 0..1 against a reference sample - 1200 random legal sixes for this board, seeded
from the map, side, enemies and bans, so every call on one board shares one scale - flips it when
the direction is minimise, and multiplies by its weight. A <b>scored constraint</b> evaluates its
bonus and penalty while its <code>when</code> holds, and its weight multiplies the difference. An
<b>assumption</b> and a prose constraint contribute nothing: they are shown, and they are the
agent's to argue with.</p>
<pre class='eq'>for one six x, with every hard limit holding:

score(x) = &Sigma; heuristics h     w_h &middot; norm_h( metric_h(x) )
         + &Sigma; scored r         w_r &middot; ( bonus_r(x) &minus; penalty_r(x) )
         &minus; &Sigma; soft limits l    penalty_l(x)

norm_h(v) = clamp( (v &minus; min_ref) / (max_ref &minus; min_ref), 0, 1 )
            and 1 &minus; that when h minimises</pre>
<p><b>What 100 means.</b> The raw score is not the number on the tile. The best six the solver
found is 100, and every other comp - yours as you pick, theirs as they reveal - is its raw score
as a share of that best. 100 means as good as the best six under this playbook on this board,
not a win probability.</p>
<p><b>The argmax.</b> Each role's pool is first cut to the top six by a fixed prior - map win
rate, plus answers to red's picks, minus exposure to them, plus synergies with the locked picks
and style fit. Every shape the limits allow is then filled from the pools around the locked
picks, each six is scored, and a local search swaps slots for same-role heroes while it improves.
Ties break by the six's mean map win rate, then by name, so the same board gives the same six
every time.</p>
<p><b>When the playbook holds only limits</b> - no heuristic, no scored constraint - the sum is
empty: every legal six scores zero, every comp on the board shows 100, and the optimal is the
tie-break alone: the highest win rates on this map that fit the shape, not a judgement about
them together. A single heuristic is what turns that ordering into an inference.</p>
<h2>How the pieces fit</h2>
<pre class='eq'>sources → db/data (fetch) → db/psql (the database) → ui/facts (FACTS of a board)
                                                                    &darr;
                   inference/strategies (STRATEGIES) → inference/solver (ARGMAX) → the board</pre>
<p><b>The data layer</b> (<code>db/</code>) pulls the sources - Blizzard's hero pages, the wiki, the
counter lists, the authored files - into one Postgres schema, and exposes it through one door:
thirty-odd MCP tools over stdio and HTTP. Everything else, including this page, reads through
those tools or the same functions behind them. A sentry container watches the strategy files and
the audit log while the stack runs.</p>
<p><b>The inference layer</b> (<code>inference/</code>) holds the playbook and the solver. It
compiles each strategy's expression once, whitelists what an expression may do, and runs the
search deterministically - no model in the loop, no network.</p>
<p><b>The board</b> (<code>ui/</code>) is this page: it turns the database into the facts of one
board and asks the inference layer for the answer at every stage of a draft - no map, a map, a
side, bans, red's picks as they reveal. Clicking around never calls a language model.</p>
<p><b>Claude's part</b> is offline and on your word: the skills and the headless agents refresh
the sources, re-derive the inferred half of a strategy from its prose, and tune the weights - then
they are done, and the deterministic pieces above serve what they left in the database and the
files. The <code>/comp</code> skill is the conversational front of the same solver.</p>
<p class='legend'>The longer version, with the folder map and the deployment, is in
<code>docs/architecture.md</code>; the schema in <code>docs/db.md</code>; the playbook's catalog in
<code>docs/inference.md</code>.</p>
</article>"""


def view_math():
    return _page("the math", MATH)


# --- server -----------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, code=200):
        self._send(json.dumps(payload, ensure_ascii=False), code, "application/json")

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/":
                return self._send(view_board())
            if path.startswith("/static/"):
                served = static_file(path[len("/static/"):])
                if served is None:
                    return self._send(_page("not found", "<p>Nothing here.</p>"), 404)
                return self._send_bytes(*served)
            if path == "/api/strategies":
                return self._json(api_strategies())
            if path == "/math":
                return self._send(view_math())
            if path not in ("/api/roster", "/api/facts", "/api/infer"):
                return self._send(_page("not found", "<p>Nothing here.</p>"), 404)
            with psycopg.connect(dsn()) as cx:      # only the data routes touch the database
                if path == "/api/roster":
                    return self._json(api_roster(cx))
                if path == "/api/facts":
                    return self._json(*api_facts(cx, query))
                return self._json(*api_infer(cx, query))
        except Exception:
            self._send(_page("error", "<pre class='warnbox'>%s</pre>"
                             % esc(traceback.format_exc())), 500)

def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("COUNTER_MATRIX_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    workers = 0 if INFERENCE_URL else inference_engine.warm()   # in-process boards split too
    print("Counter Utility Matrix: http://%s:%d%s" % (
        args.host, args.port, " (%d solver workers)" % workers if workers else ""))
    server.serve_forever()


if __name__ == "__main__":
    main()
