"""The UI LAYER's board: a map selector and a red and a blue roster,
organised and styled like the game's hero select, over the facts engine
and the inference layer.

    python -m ui.board            # serves http://localhost:8017

http.server and psycopg, no web framework. Every click re-reads the
database: the facts panel is the FactSet for (map, side, red, blue, bans);
the comps panel is the inference layer's board - red's most likely
starting comp, blue's optimal counter to the current picks, each seat's
picks scored as a share of its own optimal, the fight odds and the game
plan; the playbook panel is the strategies catalog as it sits on disk.
JSON endpoints under /api/ serve the same three things. A request that
raises is answered by db.web.failure: a Refusal 400 with its message,
anything else 500 with its type and message, the traceback on stderr.
"""

import argparse
import html
import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse

import psycopg
from psycopg.rows import TupleRow

from db import psql, web
from db.mcp.server import LOCAL_HOSTS
from inference import catalog as catalog_module
from inference import engine as inference_engine
from inference import parallel
from ui.facts import board_facts, tables
from ui.facts.draft import (
    MAX_BANS,
    TEAM_SIZE,
    board_query,
    is_sided,
    parse_board,
)

if TYPE_CHECKING:
    from db.mcp.tools import Context

# a JSON endpoint answers with a JSON object and an HTTP status
type Reply = tuple[dict[str, Any], int]
type Query = dict[str, list[str]]

STORE_REASON = "stored from the board's slider"
GITHUB_MARK = ("<svg viewBox='0 0 16 16' width='15' height='15' aria-hidden='true'><path fill='currentColor' d='M8 0C3.58 0 0 3.58 0 8"  # noqa: E501
               "c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94"  # noqa: E501
               "-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2"  # noqa: E501
               "-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0"  # noqa: E501
               " 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95"  # noqa: E501
               ".29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z'/></svg>")  # noqa: E501


# --- the settings -------------------------------------------------------------
#
# Each is read when it is used, so a change in the environment holds from the
# next request. Where the board listens is read once, by command_line().

def _http_url(setting: str) -> str:
    """A service URL from the environment without its trailing slash, "" when
    unset. The board speaks HTTP to its services, so any other scheme - a
    file: path, say - is refused."""
    value = os.environ.get(setting, "").rstrip("/")
    if value and urlparse(value).scheme not in ("http", "https"):
        raise ValueError("%s must be an http or https URL, got %r" % (setting, value))
    return value


# The inference layer runs in-process unless a service is named: in the
# compose stack the `inference` container serves it (inference/serve.py).
def inference_url() -> str:
    return _http_url("COUNTRIX_INFERENCE_URL")


# the board's one write - storing a heuristic's weight - goes to the data
# layer's `tune` tool: over HTTP to the MCP server when a URL is set (the
# compose stack), in-process through the same registry otherwise. read_only()
# below is what decides whether that write is offered at all.
def mcp_url() -> str:
    return _http_url("COUNTRIX_MCP_URL")


def mcp_token() -> str:
    return os.environ.get("COUNTRIX_MCP_TOKEN", "")


# The board writes nothing unless told it may: a weight set on the playbook tab
# rides with the session's own requests and never reaches a strategy file.
# COUNTRIX_READ_ONLY=0 brings back the store button and its one POST.
def read_only() -> bool:
    return os.environ.get("COUNTRIX_READ_ONLY", "1").lower() not in ("0", "no", "false")


# The repository the header links to; override when the repo moves.
def repo_url() -> str:
    return os.environ.get("COUNTRIX_REPO_URL", "https://github.com/mmikol/countrix")


def dsn() -> str:
    return psql.default_dsn()


def remote(
        path: str, query: Mapping[str, str | list[str]] | None = None,
        payload: dict[str, Any] | None = None) -> Reply:
    """Forward to the inference service -> (json, status)."""
    url = inference_url() + path
    if query:
        url += "?" + urlencode(query, doseq=True)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        # the scheme is http or https: inference_url() refuses any other
        with urllib.request.urlopen(request, timeout=180) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8")), response.status
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read().decode("utf-8")), error.code
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"error": "inference service returned %d" % error.code}, error.code
    except (urllib.error.URLError, OSError) as error:
        return {"error": "inference service unreachable: %s" % error}, 502


def esc(x: object) -> str:
    return html.escape(str(x if x is not None else ""))


# --- JSON endpoints ---------------------------------------------------------

def api_roster(cx: psycopg.Connection[TupleRow]) -> Reply:
    world = tables.load(cx)
    heroes = [{"name": h.name, "role": h.role, "subrole": h.subrole,
               "portrait": h.portrait, "status": h.status,
               "release_date": str(h.release_date) if h.release_date else None}
              for h in world.heroes_by_role()]
    maps = [{"name": m.name, "mode": m.mode, "style": m.style_top, "sided": is_sided(m)}
            for m in world.maps_sorted()]
    return {"heroes": heroes, "maps": maps, "role_icons": world.role_icons,
            "newer_patches": world.newer_patches}, 200


def api_facts(cx: psycopg.Connection[TupleRow], query: Query) -> Reply:
    draft = parse_board(query)
    world = tables.load(cx)
    return board_facts.generate(world, draft).to_dict(), 200


def api_infer(cx: psycopg.Connection[TupleRow], query: Query) -> Reply:
    """The board solved at this stage of the draft - the inference layer's
    `board()`. The playbook tab's sliders ride along as `weights=<id>:<0..10>`,
    one per heuristic set away from its file."""
    draft = parse_board(query)
    # a malformed weight is refused here, never forwarded
    weights = catalog_module.parse_weights(query.get("weights", []))
    if inference_url():
        forward = board_query(draft)
        if weights:
            forward["weights"] = ["%s:%g" % kv for kv in sorted(weights.items())]
        return remote("/board", forward)
    world = tables.load(cx)
    return inference_engine.board(world, draft, weights=weights).to_dict(), 200


def mcp_call(name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any] | None, bool]:
    """One tools/call on the MCP server -> (text, structured, is_error)."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = mcp_token()
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(mcp_url(), data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return "the MCP server answered %d" % error.code, None, True
    except (urllib.error.URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return "the MCP server is unreachable: %s" % error, None, True
    if "error" in reply:
        return str(reply["error"].get("message", reply["error"])), None, True
    result = reply.get("result") or {}
    text = "\n".join(c.get("text", "") for c in result.get("content", [])
                     if c.get("type") == "text")
    return text, result.get("structuredContent"), bool(result.get("isError"))


def tool_context() -> "Context":
    from db.mcp import tools
    return tools.Context(dsn=dsn())


def api_weight(payload: dict[str, Any]) -> Reply:
    """Store a heuristic's weight in its file - the slider's "store". The
    change goes through the `tune` tool (validated, logged in the tuning
    log with its reason, mirrored into the database), never around it. The
    tool's refusal is relayed as 400 over HTTP and raised in-process, where
    the POST's boundary answers it 400 the same way."""
    hid = str((payload or {}).get("id") or "")
    if not catalog_module.ID_RE.fullmatch(hid):
        return {"error": "no such heuristic"}, 400
    raw: Any = payload.get("weight")         # any JSON: float() refuses what is not a number
    try:
        weight = round(float(raw), 2)
    except (TypeError, ValueError):
        return {"error": "the weight must be a number"}, 400
    if not 0.0 <= weight <= 10.0:
        return {"error": "the weight must be within 0..10"}, 400
    arguments = {"id": hid, "field": "weight", "value": weight, "reason": STORE_REASON,
                 "by": "the board"}
    if mcp_url():
        text, change, failed = mcp_call("tune", arguments)
        if failed:
            return {"error": text}, 400
        return {"line": text.split("\n")[0], "change": change}, 200
    from db.mcp import tools
    text, stored = tools.run_tool(tool_context(), "tune", **arguments)
    return {"line": text.split("\n")[0], "change": stored}, 200


def api_strategies() -> Reply:
    if inference_url():
        return remote("/strategies")
    # a playbook that does not load is the server's fault: a 500, as on the service
    catalog = catalog_module.load()
    return {"strategies": [h.to_dict() for h in catalog],
            "playbook": catalog_module.playbook_name()}, 200


# --- the board page ---------------------------------------------------------
#
# The page is a shell over the static files: board.js loads last because it
# calls into comps.js and playbook.js, and TEAM and BANS come from the page so
# the scripts keep no constant in step with the Python.

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_TYPES = {".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8"}


def static_file(name: str) -> tuple[bytes, str] | None:
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


def view_board() -> str:
    return (HEAD + "<title>Countrix</title><main>"
            "<header class='top'><h1>Countrix"
            "<span class='expand'> the counter utility matrix</span></h1>"
            "<div class='mapsel'><select id='mapsel'></select><span class='mode' id='mode'></span>"
            "<span class='sideseg' id='sideseg' title=\"blue's side;"
            " red gets the other\">"
            "<button data-side='attack'>attack</button><button data-side='defense'>defense</button>"
            "</span>"
            "<button id='clearall' title='the map, the side, the bans and both teams'>"
            "clear all</button>"
            "<span class='flash' id='flash'></span></div>"
            "<span class='links'><a class='mathlink' href='/math'>the math</a>"
            "<a class='mathlink' href='/tests'>the tests</a>"
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
            "</main><script>var TEAM = %d, BANS = %d, READ_ONLY = %s;</script>"
            "<script src='/static/comps.js'></script>"
            "<script src='/static/playbook.js'></script>"
            "<script src='/static/board.js'></script>"
            % (repo_url(), GITHUB_MARK, TEAM_SIZE, MAX_BANS, "true" if read_only() else "false"))


# --- the math page -------------------------------------------------------------

def _page(title: str, body: str) -> str:
    return (HEAD + "<title>%s</title>"
            "<main><header class='top'><h1><a href='/'>Counter <span>Utility Matrix</span></a></h1>"
            "</header>%s</main>" % (esc(title), body))


def view_math() -> str:
    """The math page: ui/static/math.html, the article alone, in the page shell."""
    with open(os.path.join(STATIC_DIR, "math.html"), encoding="utf-8") as handle:
        return _page("the math", handle.read())


def view_tests() -> str:
    """The tests page: what is checked, how, and what none of it proves."""
    with open(os.path.join(STATIC_DIR, "tests.html"), encoding="utf-8") as handle:
        return _page("the tests", handle.read())


# --- server -----------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _send(self, body: str, code: int = 200, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: dict[str, Any], code: int = 200) -> None:
        self._send(json.dumps(payload, ensure_ascii=False), code, "application/json")

    def _origin_allowed(self) -> bool:
        """The same DNS-rebinding guard the data layer's door applies: a browser
        sends Origin, and only a local one may reach the board's one write."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlparse(origin).hostname in LOCAL_HOSTS

    def _failed(self, path: str, error: Exception) -> None:
        """A request that raised answers in the shape the route promised: JSON
        under /api/, the error page for a page, in the words and status
        db.web.failure gives it - never a traceback."""
        reply = web.failure(error)
        if path.startswith("/api/"):
            return self._json(reply.body, reply.status)
        return self._send(_page("error", "<pre class='warnbox'>%s</pre>"
                                % esc(reply.body["error"])), reply.status)

    def _not_found(self, path: str) -> None:
        if path.startswith("/api/"):
            return self._json({"error": "nothing here"}, 404)
        return self._send(_page("not found", "<p>Nothing here.</p>"), 404)

    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/weight":
            return self._json({"error": "nothing here"}, 404)
        if not self._origin_allowed():
            return self._json({"error": "origin not allowed"}, 403)
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json({"error": "a JSON body is required"}, 415)
        if read_only():
            return self._json({"error": "this board does not write: a weight applies to your"
                                        " session only"}, 403)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json({"error": "a numeric Content-Length is required"}, 400)
        if not 0 < length <= 4096:
            return self._json({"error": "a small JSON body is required"}, 400)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json({"error": "bad JSON"}, 400)
        # "bad JSON" means only that: what the store raises is its own answer
        try:
            return self._json(*api_weight(payload if isinstance(payload, dict) else {}))
        except Exception as error:  # noqa: BLE001  # the request boundary
            return self._failed(path, error)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/":
                return self._send(view_board())
            if path.startswith("/static/"):
                served = static_file(path[len("/static/"):])
                if served is None:
                    return self._not_found(path)
                return self._send_bytes(*served)
            if path == "/api/strategies":
                return self._json(*api_strategies())
            if path == "/math":
                return self._send(view_math())
            if path == "/tests":
                return self._send(view_tests())
            if path not in ("/api/roster", "/api/facts", "/api/infer"):
                return self._not_found(path)
            with psycopg.connect(dsn()) as cx:      # only the data routes touch the database
                if path == "/api/roster":
                    return self._json(*api_roster(cx))
                if path == "/api/facts":
                    return self._json(*api_facts(cx, query))
                return self._json(*api_infer(cx, query))
        except Exception as error:  # noqa: BLE001  # the request boundary
            return self._failed(path, error)


def command_line(argv: list[str] | None = None) -> argparse.Namespace:
    """The command line. Where the board listens defaults to COUNTRIX_UI_HOST
    and COUNTRIX_UI_PORT, both read when the board starts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("COUNTRIX_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("COUNTRIX_UI_PORT", "8017")))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Serve the board. A service URL with a scheme other than http or https
    stops it here, before it binds the port."""
    args = command_line(argv)
    try:
        inference = inference_url()
        mcp_url()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    workers = 0 if inference else parallel.warm()   # in-process boards split too
    print("Countrix: http://%s:%d%s" % (
        args.host, args.port, " (%d solver workers)" % workers if workers else ""))
    server.serve_forever()


if __name__ == "__main__":
    main()
