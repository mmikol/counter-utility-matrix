"""The UI LAYER's board: a map selector and a red and a blue roster,
organised and styled like the game's hero select, over the facts engine
and the inference layer.

    python -m ui.board            # serves http://localhost:8017

Standard library only. Every click re-reads the database: the facts
panel is the FactSet for (map, side, red, blue, bans); the comps panel is
the inference layer's board - red's most likely starting comp, blue's
optimal counter to the current picks, each seat's picks scored as a share
of its own optimal, the fight odds and the game plan; the playbook panel
is the strategies catalog as it sits on disk. JSON endpoints under /api/
serve the same three things.
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
from ui.facts.compute import MAX_BANS, SIDED_MODES, TEAM_SIZE

PORT = int(os.environ.get("COUNTER_MATRIX_UI_PORT", "8017"))

# The inference layer runs in-process unless a service is named: in the
# compose stack the `inference` container serves it (inference/serve.py).
INFERENCE_URL = os.environ.get("INFERENCE_URL", "").rstrip("/")
# the board's one write - storing a heuristic's weight - goes to the data
# layer's `tune` tool: over HTTP to the MCP server when a URL is set (the
# compose stack), in-process through the same registry otherwise
MCP_URL = os.environ.get("COUNTER_MATRIX_MCP_URL", "").rstrip("/")
MCP_TOKEN = os.environ.get("COUNTER_MATRIX_MCP_TOKEN", "")
STORE_REASON = "stored from the board's slider"
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
    bans = [x for x in query.get("ban", []) if x][:MAX_BANS]
    side = (query.get("side") or [""])[0]
    return map_name, red, blue, bans, side


def api_roster(cx):
    world = model.load(cx)
    heroes = [{"name": h.name, "role": h.role, "subrole": h.subrole,
               "portrait": h.portrait, "status": h.status,
               "release_date": str(h.release_date) if h.release_date else None}
              for h in world.heroes_by_role()]
    maps = [{"name": m.name, "mode": m.mode, "style": m.style_top,
             "sided": (m.mode or "") in SIDED_MODES}
            for m in world.maps_sorted()]
    return {"heroes": heroes, "maps": maps, "role_icons": world.role_icons,
            "newer_patches": world.newer_patches}


def api_facts(cx, query):
    map_name, red, blue, bans, side = _board(query)
    world = model.load(cx)
    try:
        fs = facts_engine.generate(world, map_name, red, blue, bans, side)
    except ValueError as error:
        return {"error": str(error)}, 400
    return fs.to_dict(), 200


def api_infer(cx, query):
    """The board solved at this stage of the draft - the inference layer's
    `board()`. The playbook tab's sliders ride along as `weight=<id>:<0..10>`,
    one per heuristic set away from its file."""
    map_name, red, blue, bans, side = _board(query)
    weights = catalog_module.parse_weights(query.get("weight", []))
    if INFERENCE_URL:
        query = {"map": map_name or "", "side": side, "red": red, "blue": blue, "ban": bans}
        if weights:
            query["weight"] = ["%s:%g" % kv for kv in sorted(weights.items())]
        return remote("/board", query)
    world = model.load(cx)
    try:
        b = inference_engine.board(world, map_name, red, blue, bans, side, weights=weights)
    except ValueError as error:
        return {"error": str(error)}, 400
    return inference_engine.board_dict(b), 200


def mcp_call(name, arguments):
    """One tools/call on the MCP server -> (text, structured, is_error)."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if MCP_TOKEN:
        headers["Authorization"] = "Bearer " + MCP_TOKEN
    request = urllib.request.Request(MCP_URL, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return "the MCP server answered %d" % error.code, None, True
    except (urllib.error.URLError, OSError, ValueError) as error:
        return "the MCP server is unreachable: %s" % error, None, True
    if "error" in reply:
        return str(reply["error"].get("message", reply["error"])), None, True
    result = reply.get("result") or {}
    text = "\n".join(c.get("text", "") for c in result.get("content", [])
                     if c.get("type") == "text")
    return text, result.get("structuredContent"), bool(result.get("isError"))


def tool_context():
    from db.mcp import tools
    return tools.Context(dsn=dsn())


def api_weight(payload):
    """Store a heuristic's weight in its file - the slider's "store". The
    change goes through the `tune` tool (validated, logged in the tuning
    log with its reason, mirrored into the database), never around it."""
    from inference import tune
    hid = str((payload or {}).get("id") or "")
    if not tune.ID_RE.fullmatch(hid):
        return {"error": "no such heuristic"}, 400
    try:
        weight = round(float(payload.get("weight")), 2)
    except (TypeError, ValueError):
        return {"error": "the weight must be a number"}, 400
    if not 0.0 <= weight <= 10.0:
        return {"error": "the weight must be within 0..10"}, 400
    arguments = {"id": hid, "field": "weight", "value": weight, "reason": STORE_REASON,
                 "by": "the board"}
    if MCP_URL:
        text, change, failed = mcp_call("tune", arguments)
        if failed:
            return {"error": text}, 400
        return {"line": text.split("\n")[0], "change": change}, 200
    from db.mcp import tools
    try:
        text, change = tools.run_tool(tool_context(), "tune", **arguments)
    except tools.ToolError as error:
        return {"error": str(error)}, 400
    return {"line": text.split("\n")[0], "change": change}, 200


def api_strategies():
    if INFERENCE_URL:
        return remote("/strategies")[0]
    catalog = catalog_module.load()
    return {"strategies": [h.to_dict() for h in catalog],
            "playbook": catalog_module.playbook_name()}


# --- the board page ---------------------------------------------------------
#
# The page is a shell over the static files: board.js loads last because it
# calls into comps.js and playbook.js, and TEAM and BANS come from the page so
# the scripts keep no constant in step with the Python.

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
            "<span class='sideseg' id='sideseg' title=\"blue's side;"
            " red gets the other\">"
            "<button data-side='attack'>attack</button><button data-side='defense'>defense</button>"
            "</span>"
            "<button id='clearall' title='the map, the side, the bans and both teams'>"
            "clear all</button>"
            "<span class='flash' id='flash'></span></div>"
            "<span class='links'><a class='mathlink' href='/math'>the math</a>"
            "<a class='gh' href='%s' target='_blank' rel='noopener'>%s GitHub</a>"
            "</span>"
            "</header>"
            "<div class='bans' id='bans'><div class='banhead' id='banhead'"
            " title='open or close the ban picker'>"
            "<h3>bans</h3><span class='bancount' id='bancount'>"
            "</span><span class='banmini' id='banmini'></span>"
            "<span class='caret'>&#9656;</span></div>"
            "<div class='banbody'><div class='slots' id='banslots'></div>"
            "<div class='roles' id='banroster'></div></div></div>"
            "<div class='warnbox' id='vintage' style='display:none'></div>"
            "<div class='momentum' id='momentum'></div>"
            "<div class='teams'>"
            "<section class='team blue'><h2>blue team <span class='tscore' id='bluescore'"
            " title=\"your picks as a share of blue's optimal\">"
            "</span>"
            "<button class='clearteam' data-clear='blue'>clear</button>"
            "</h2>"
            "<div class='slots' id='blueslots'></div><div class='roles' id='blueroster'>"
            "</div></section>"
            "<section class='team red'><h2>red team <span class='tscore' id='redscore'"
            " title=\"their picks as a share of their best counter to yours\">"
            "</span>"
            "<button class='clearteam' data-clear='red'>clear</button>"
            "</h2>"
            "<div class='slots' id='redslots'></div><div class='roles' id='redroster'>"
            "</div></section>"
            "</div>"
            "<nav class='tabs'><button data-tab='comps'>comps</button>"
            "<button data-tab='facts'>facts</button>"
            "<button data-tab='playbook'>playbook</button></nav>"
            "<section class='panel' id='tab-comps'><div class='plan' id='plan'>"
            "</div><div class='seats'>"
            "<div class='seat blue' id='inf-blue'></div><div class='seat red' id='inf-red'>"
            "</div></div></section>"
            "<section class='panel' id='tab-facts'><div class='tools'>"
            "<input type='text' id='filter' placeholder='filter'>"
            "<span id='chips'></span><span id='factsn' class='count'></span></div>"
            "<table class='facts'><tbody id='factbody'></tbody></table></section>"
            "<section class='panel' id='tab-playbook'><div id='playbook'></div></section>"
            "</main><script>var TEAM = %d, BANS = %d;</script>"
            "<script src='/static/comps.js'></script>"
            "<script src='/static/playbook.js'></script>"
            "<script src='/static/board.js'></script>"
            % (REPO_URL, GITHUB_MARK, TEAM_SIZE, MAX_BANS))


# --- the math page -------------------------------------------------------------

def _page(title, body):
    return (HEAD + "<title>%s</title>"
            "<main><header class='top'><h1><a href='/'>Counter <span>Utility Matrix</span></a></h1>"
            "</header>%s</main>" % (esc(title), body))


def view_math():
    """The math page: ui/static/math.html, the article alone, in the page shell."""
    with open(os.path.join(STATIC_DIR, "math.html"), encoding="utf-8") as handle:
        return _page("the math", handle.read())


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

    def do_POST(self):
        if urlparse(self.path).path != "/api/weight":
            return self._json({"error": "nothing here"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 4096:
                return self._json({"error": "a small JSON body is required"}, 400)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            return self._json(*api_weight(payload if isinstance(payload, dict) else {}))
        except ValueError:
            return self._json({"error": "bad JSON"}, 400)
        except Exception:
            self._send(_page("error", "<pre class='warnbox'>%s</pre>"
                             % esc(traceback.format_exc())), 500)

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
