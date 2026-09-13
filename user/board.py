"""The USER LAYER's board: a map selector and a red and a blue roster,
organised and styled like the game's hero select, over the facts engine
and the inference layer.

    python -m user.board            # serves http://localhost:8017

Standard library only. Every click re-reads the database: the facts
panel is the FactSet for (map, red, blue), the optimal-comp panel is the
inference layer's answer around the locked blue picks (or the evaluation
of a full six), and the playbook panel is the strategies catalog as it
sits on disk. JSON endpoints under /api/ serve the same three things.
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

from data import common
from user.facts import engine as facts_engine
from user.facts import model
from user.facts.compute import SIDED_MODES, TEAM_SIZE
from inference import catalog as catalog_module
from inference import engine as inference_engine
from inference import record as record_module

PORT = int(os.environ.get("OVERWATCH_DB_UI_PORT", "8017"))

# The inference layer runs in-process unless a service is named: in the
# compose stack the `inference` container serves it (inference/serve.py).
INFERENCE_URL = os.environ.get("INFERENCE_URL", "").rstrip("/")


def dsn():
    return common.default_dsn()


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
               "pool": h.pool, "portrait": h.portrait,
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


def api_recs(cx):
    row = cx.execute("""select r.rec_id, r.playstyle,
            (select string_agg(h.name, ', ' order by p.position)
             from recommendation_picks p join heroes h using(hero_id)
             where p.rec_id = r.rec_id)
            from recommendations r order by rec_id desc limit 1""").fetchone()
    if not row:
        return {"latest": 0, "summary": ""}
    rec_id, playstyle, picks = row
    return {"latest": rec_id, "summary": "%s (%s)" % (picks or "", playstyle)}


def api_record(cx, payload):
    if INFERENCE_URL:
        return remote("/record", payload=payload)
    try:
        rec_id, path = record_module.record(
            cx, payload.get("question") or "recorded from the board",
            payload["answer"], payload.get("map"), payload.get("red", []),
            payload.get("blue", []), payload.get("model", "board"),
            payload.get("bans", []), payload.get("side", ""))
    except (ValueError, KeyError) as error:
        return {"error": str(error)}, 400
    return {"rec_id": rec_id, "transcript": os.path.relpath(path, common.ROOT)}, 200


# --- the board page ---------------------------------------------------------
#
# The page is a shell: the stylesheet and the script are static files under
# user/static/ (editable and lintable on their own), served by this same
# handler; TEAM and BANS come from the page so the script has no constant
# to keep in step.

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_TYPES = {".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8"}


def static_file(name):
    """(bytes, content type) for a file under user/static, or None."""
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
    return (HEAD + "<title>overwatch-db board</title><main>"
            "<header class='top'><h1>overwatch<span>-db</span></h1>"
            "<span class='sub' title='FACTS = HEROES ∪ MAPS ∪ META (authoritative: pulled and set)"
            "&#10;STRATEGIES = CONSTRAINTS ∪ HEURISTICS (the playbook: markdown files, tuned by what history shows)"
            "&#10;COMP = ARGMAX[ STRATEGIES( FACTS ) ]'>"
            "FACTS = HEROES ∪ MAPS ∪ META &nbsp; STRATEGIES = CONSTRAINTS ∪ HEURISTICS &nbsp; "
            "COMP = ARGMAX[ STRATEGIES( FACTS ) ] &nbsp;·&nbsp; "
            "<a href='/recs'>recorded comps</a> &nbsp;·&nbsp; <span id='captured'></span></span>"
            "<div class='mapsel'><select id='mapsel'></select><span class='mode' id='mode'></span>"
            "<span class='sideseg' id='sideseg' title='blue attacks or defends; red gets the other side'>"
            "<button data-side='attack'>attack</button><button data-side='defense'>defense</button></span>"
            "<button id='swapbtn' title='swap red and blue'>swap sides</button>"
            "<button id='clearbtn'>new game</button><span class='status' id='status'></span></div>"
            "</header>"
            "<div class='bans'><h3>bans</h3><span id='banslots'></span>"
            "<select id='bansel'></select>"
            "<span class='hint'>up to five, all optional: each team's two and the lobby's -"
            " a banned hero leaves both rosters and the search</span></div>"
            "<div class='warnbox' id='vintage' style='display:none'></div>"
            "<div class='notice' id='newrec'></div>"
            "<div class='teams'>"
            "<section class='team red'><h2>red team <small>the enemy - click their heroes as they reveal</small>"
            "<small style='margin-left:auto' id='redcount'></small></h2>"
            "<div class='slots' id='redslots'></div><div class='roles' id='redroster'></div></section>"
            "<section class='team blue'><h2>blue team <small>your locked picks - the inference layer fills the rest</small>"
            "<small style='margin-left:auto' id='bluecount'></small></h2>"
            "<div class='slots' id='blueslots'></div><div class='roles' id='blueroster'></div></section>"
            "</div>"
            "<nav class='tabs'><button data-tab='facts'>facts <span id='factsn'></span></button>"
            "<button data-tab='inf'>optimal comps</button><button data-tab='cur'>current comp</button>"
            "<button data-tab='playbook'>playbook</button></nav>"
            "<section class='panel' id='tab-facts'><div class='tools'>"
            "<input type='text' id='filter' placeholder='filter facts - try a hero, CAUTION, derived:, team.'>"
            "<span id='chips'></span></div>"
            "<table class='facts'><tbody id='factbody'></tbody></table>"
            "<p class='legend'>every line is a row or a formula over the database, numbered for citation;"
            " the /comp skill and the inference layer read exactly these.</p></section>"
            "<section class='panel' id='tab-inf'><div class='seat blue' id='inf-blue'></div>"
            "<div class='seat red' id='inf-red'></div></section>"
            "<section class='panel' id='tab-cur'><div class='seat blue' id='cur'></div></section>"
            "<section class='panel' id='tab-playbook'><div id='playbook'></div></section>"
            "</main><script>var TEAM = %d, BANS = 5;</script>"
            "<script src='/static/board.js'></script>" % TEAM_SIZE)


# --- recorded recommendations -------------------------------------------------

def _page(title, body):
    return (HEAD + "<title>%s</title>"
            "<main><header class='top'><h1><a href='/'>overwatch<span>-db</span></a></h1>"
            "<span class='sub'>%s</span></header>%s</main>" % (esc(title), esc(title), body))


def view_recs(cx):
    rows = cx.execute("""select rec_id, created_at::date, request, playstyle, model
                         from recommendations order by rec_id desc limit 50""").fetchall()
    body = "".join("<tr><td><a href='/rec/%d'>#%d</a></td><td>%s</td><td>%s</td><td>%s</td>"
                   "<td>%s</td></tr>" % (r, r, d, esc(q[:80]), esc(p), esc(m))
                   for r, d, q, p, m in rows) or "<tr><td>none yet</td></tr>"
    return _page("recorded compositions", "<table class='rec-list'><tr><th>id</th><th>date</th>"
                 "<th>question</th><th>comp</th><th>model</th></tr>%s</table>" % body)


def view_rec(cx, rec_id):
    rec = cx.execute("""select request, coalesce(m.name,'-'), model, playstyle,
                   reasoning, created_at::date from recommendations r
                   left join maps m using(map_id) where rec_id=%s""", (rec_id,)).fetchone()
    if not rec:
        return _page("not found", "<p>No recommendation #%d.</p>" % rec_id)
    request, map_name, model_name, playstyle, reasoning, day = rec
    picks = cx.execute("""select h.name, p.why,
        coalesce((select string_agg(e.tag, ', ' order by length(e.tag), e.tag)
            from recommendation_evidence e
            where e.rec_id=p.rec_id and e.hero_id=p.hero_id), '')
        from recommendation_picks p join heroes h using(hero_id)
        where p.rec_id=%s order by p.position""", (rec_id,)).fetchall()
    cited = cx.execute("""select distinct tag, source_table, description
                     from recommendation_evidence where rec_id=%s
                     order by length(tag), tag""", (rec_id,)).fetchall()
    picks_html = "".join(
        "<div class='hcard'><b>%s</b> <span class='ev'>%s</span><p>%s</p></div>"
        % (esc(h), esc(tags), esc(why)) for h, why, tags in picks)
    ev = "".join("<tr><td class='tag'>[%s]</td><td class='text'>%s</td><td class='src'>%s</td></tr>"
                 % (esc(t), esc(d), esc(tb)) for t, tb, d in cited)
    return _page("recommendation #%d" % rec_id, """
        <h2>Recommendation #%d - %s</h2>
        <p class='legend'>%s &nbsp;·&nbsp; map: %s &nbsp;·&nbsp; %s</p>
        <p>%s</p><h3>Comp - %s</h3><div class='hcards'>%s</div>
        <h3>Facts cited</h3><table class='facts'>%s</table>""" % (
        rec_id, day, esc(model_name), esc(map_name), esc(request),
        esc(reasoning), esc(playstyle), picks_html, ev))


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
            with psycopg.connect(dsn()) as cx:
                if path == "/api/roster":
                    return self._json(api_roster(cx))
                if path == "/api/facts":
                    return self._json(*api_facts(cx, query))
                if path == "/api/infer":
                    return self._json(*api_infer(cx, query))
                if path == "/api/recs":
                    return self._json(api_recs(cx))
                if path == "/recs":
                    return self._send(view_recs(cx))
                if path.startswith("/rec/"):
                    return self._send(view_rec(cx, int(path[5:])))
            self._send(_page("not found", "<p>Nothing here.</p>"), 404)
        except Exception:
            self._send(_page("error", "<pre class='warnbox'>%s</pre>"
                             % esc(traceback.format_exc())), 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if parsed.path == "/api/record":
                with psycopg.connect(dsn()) as cx:
                    return self._json(*api_record(cx, payload))
            self._json({"error": "nothing here"}, 404)
        except Exception as error:
            self._json({"error": str(error)}, 500)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("OVERWATCH_DB_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("overwatch-db board: http://%s:%d" % (args.host, args.port))
    server.serve_forever()


if __name__ == "__main__":
    main()
