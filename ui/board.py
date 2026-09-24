"""The board: a map selector and a red and a blue roster, organised and
styled like the game's hero select, over the facts layer and the inference
layer.

    python -m ui.board            # serves http://localhost:8017

http.server and psycopg, no web framework, no build step. This module is
the board's server - its settings, its JSON endpoints and the handler that
routes to them and to the pages ui/pages.py renders. Every click re-reads
the database: the facts panel is the FactSet for (map, side, red, blue, bans);
the comps panel is the inference layer's board - red's most likely starting
comp, blue's picks filled and its optimal counter to red's, each seat's
picks scored as a share of its own optimal, the fight odds and the game
plan; the playbook panel is the strategies catalog as it sits on disk.
JSON endpoints under /api/ serve the same three things.

A request whose Host or Origin names another server is refused with 403
before it is routed (db.web's guard; --allow-host adds a name the board is
published under). A request that raises is answered by db.web.failure: a
Refusal 400 with its message, anything else 500 with its type and message,
the traceback on stderr. Every board solved, and every request that fails,
leaves a line on stderr.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlencode, urlsplit

import psycopg
from psycopg.rows import TupleRow

from db import psql, web
from door.mcp import tools
from facts import board_facts, tables
from facts.draft import Draft, board_query, is_sided, parse_board
from inference import catalog as catalog_module
from inference import engine, parallel, supersede
from ui import pages

# a parsed query string; a JSON endpoint answers it with a db.web.Reply, a JSON
# object and an HTTP status
type Query = Mapping[str, Sequence[str]]

STORE_REASON = "stored from the board's slider"
MAX_WEIGHT_BODY = 4096        # bytes: a weight is a two-field JSON object
REMOTE_TIMEOUT = 180          # seconds a board may take on the inference service


# --- the settings -------------------------------------------------------------
#
# Each is read when it is used, so a change in the environment holds from the
# next request. Where the board listens is read once, by command_line().

def _http_url(setting: str) -> str:
    """A service URL from the environment without its trailing slash, "" when
    unset. The board speaks HTTP to its services, so any other scheme - a
    file: path, say - is refused."""
    value = os.environ.get(setting, "").rstrip("/")
    if value and urlsplit(value).scheme not in ("http", "https"):
        raise ValueError("%s must be an http or https URL, got %r" % (setting, value))
    return value


# The inference layer runs in-process unless a service is named: in the
# compose stack the `inference` container serves it (inference/serve.py).
def inference_url() -> str:
    return _http_url("COUNTRIX_INFERENCE_URL")


# the board's one write - storing a heuristic's weight - goes to the door's
# `tune` tool: over HTTP to the MCP server when a URL is set (the
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


def remote(
        path: str, query: Mapping[str, str | Sequence[str]] | None = None,
        payload: object = None) -> web.Reply:
    """Forward to the inference service -> its reply. A service that does
    not answer is a 502, and a line on stderr naming why."""
    url = inference_url() + path
    if query:
        url += "?" + urlencode(query, doseq=True)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        # the scheme is http or https: inference_url() refuses any other
        with urllib.request.urlopen(request, timeout=REMOTE_TIMEOUT) as response:  # nosec B310
            return web.Reply(json.loads(response.read().decode("utf-8")), response.status)
    except urllib.error.HTTPError as error:
        try:
            return web.Reply(json.loads(error.read().decode("utf-8")), error.code)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.Reply({"error": "inference service returned %d" % error.code}, error.code)
    except (urllib.error.URLError, OSError) as error:
        sys.stderr.write(
            "countrix board: the inference service at %s did not answer %s: %s\n"
            % (inference_url(), path, error))
        return web.Reply({"error": "inference service unreachable: %s" % error}, 502)


# --- JSON endpoints ---------------------------------------------------------

def api_roster(cx: psycopg.Connection[TupleRow]) -> web.Reply:
    world = tables.load(cx)
    heroes = [
        {"name": h.name, "role": h.role, "subrole": h.subrole, "portrait": h.portrait,
            "status": h.status, "release_date": str(h.release_date) if h.release_date else None}
        for h in world.heroes_by_role()]
    maps = [{"name": m.name, "mode": m.mode, "style": m.style_top, "sided": is_sided(m)}
            for m in world.maps_sorted()]
    return web.Reply({"heroes": heroes, "maps": maps, "role_icons": world.role_icons,
                      "newer_patches": world.newer_patches}, 200)


def api_facts(cx: psycopg.Connection[TupleRow], query: Query) -> web.Reply:
    draft = parse_board(query)
    world = tables.load(cx)
    return web.Reply(board_facts.generate(world, draft).to_dict(), 200)


def api_board(query: Query) -> web.Reply:
    """The board solved at this stage of the draft - the inference layer's
    `board()`: on the service when one is named, else in this process, the
    one branch that opens a connection. The playbook tab's sliders ride along
    as `weights=<id>:<0..10>`, one per heuristic set away from its file, and
    the page names itself as `client`, so its newer board supersedes one
    still solving. A malformed weight is refused here, never forwarded."""
    draft = parse_board(query)
    weights = catalog_module.parse_weights(query.get("weights", []))
    client = (query.get("client") or [""])[0]
    if inference_url():
        forward: dict[str, str | list[str]] = dict(board_query(draft))
        if weights:
            forward["weights"] = ["%s:%g" % kv for kv in sorted(weights.items())]
        if client:
            forward["client"] = client
        return remote("/board", forward)
    superseded = supersede.LATEST.take(client)
    with psycopg.connect(psql.default_dsn()) as cx:
        return solve_board(cx, draft, weights, superseded)


def solve_board(
        cx: psycopg.Connection[TupleRow], draft: Draft,
        weights: Mapping[str, float] | None = None,
        superseded: Callable[[], bool] | None = None) -> web.Reply:
    """The board solved in this process as the page asks for it: under the
    sliders' weights, without the countered case the page never reads, and
    stopped once `superseded` reports a newer board from the same page. A
    Refusal reaches the request's boundary, which answers it 400."""
    world = tables.load(cx)
    brief = engine.Brief(weights=weights, countered=False, superseded=superseded)
    return web.Reply(engine.board(world, draft, brief=brief).to_dict(), 200)


def tool_context() -> tools.Context:
    """Where an in-process tool call lands: the database default_dsn() names."""
    return tools.Context()


def api_weight(payload: Mapping[str, object] | None) -> web.Reply:
    """Store a heuristic's weight in its file - the slider's "store". The
    change goes through the `tune` tool (validated, logged in the tuning
    log with its reason, mirrored into the database), never around it. The
    tool's refusal is relayed as 400 over HTTP and raised in-process, where
    the POST's boundary answers it 400 the same way."""
    payload = payload or {}
    hid = str(payload.get("id") or "")
    if not catalog_module.ID_RE.fullmatch(hid):
        return web.Reply({"error": "no such heuristic"}, 400)
    raw = payload.get("weight")
    try:
        if not isinstance(raw, (int, float, str)):
            raise TypeError(raw)
        weight = round(float(raw), 2)
    except (TypeError, ValueError):
        return web.Reply({"error": "the weight must be a number"}, 400)
    if not 0.0 <= weight <= 10.0:
        return web.Reply({"error": "the weight must be within 0..10"}, 400)
    arguments = {
        "id": hid, "field": "weight", "value": weight, "reason": STORE_REASON, "by": "the board"}
    if mcp_url():
        reply = web.call_tool(mcp_url(), "tune", arguments, token=mcp_token())
        if reply.is_error:
            return web.Reply({"error": reply.text}, 400)
        return web.Reply({"line": reply.text.split("\n")[0], "change": reply.structured}, 200)
    text, stored = tools.run_tool(tool_context(), "tune", **arguments)
    return web.Reply({"line": text.split("\n")[0], "change": stored}, 200)


def api_strategies() -> web.Reply:
    if inference_url():
        return remote("/strategies")
    # a playbook that does not load is the server's fault: a 500, as on the service
    catalog = catalog_module.load()
    return web.Reply({"strategies": [h.to_dict() for h in catalog],
                      "playbook": catalog_module.playbook_name()}, 200)


# --- server -----------------------------------------------------------------

class Handler(web.Handler):
    timed = frozenset({"/api/board"})

    def _html(self, body: str, code: int = 200) -> None:
        self._send(body.encode("utf-8"), "text/html; charset=utf-8", code)

    def _failed(self, path: str, error: Exception) -> None:
        """A request that raised answers in the shape the route promised: JSON
        under /api/, the error page for a page, in the words and status
        db.web.failure gives it - never a traceback."""
        reply = web.failure(error)
        if path.startswith("/api/"):
            return self._json(reply.body, reply.status)
        page = pages.page("error", "<pre class='warnbox'>%s</pre>" % pages.esc(reply.body["error"]))
        return self._html(page, reply.status)

    def _not_found(self, path: str) -> None:
        if path.startswith("/api/"):
            return self._json({"error": "nothing here"}, 404)
        return self._html(pages.page("not found", "<p>Nothing here.</p>"), 404)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path != "/api/weight":
            return self._json({"error": "nothing here"}, 404)
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json({"error": "a JSON body is required"}, 415)
        if read_only():
            return self._json({"error": "this board does not write: a weight applies to your"
                                        " session only"}, 403)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json({"error": "a numeric Content-Length is required"}, 400)
        if not 0 < length <= MAX_WEIGHT_BODY:
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
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/":
                return self._html(pages.view_board(read_only()))
            if path.startswith("/static/"):
                served = pages.static_file(path[len("/static/"):])
                if served is None:
                    return self._not_found(path)
                return self._send(
                    served.body, served.content_type, headers={"Cache-Control": "no-cache"})
            if path == "/math":
                return self._html(pages.view_math())
            if path == "/tests":
                return self._html(pages.view_tests())
            if path == "/api/strategies":
                return self._json(*api_strategies())
            if path == "/api/board":              # connects only when it solves here
                return self._json(*api_board(query))
            if path not in ("/api/roster", "/api/facts"):
                return self._not_found(path)
            with psycopg.connect(psql.default_dsn()) as cx:
                if path == "/api/roster":
                    return self._json(*api_roster(cx))
                return self._json(*api_facts(cx, query))
        except Exception as error:  # noqa: BLE001  # the request boundary
            return self._failed(path, error)


def command_line(argv: list[str] | None = None) -> argparse.Namespace:
    """The command line. Where the board listens defaults to COUNTRIX_UI_HOST
    and COUNTRIX_UI_PORT, both read when the board starts; --allow-host,
    repeated, names a host it answers to beside the local ones - the public
    name of a published board, without which every request answers 403."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("COUNTRIX_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("COUNTRIX_UI_PORT", "8017")))
    parser.add_argument("--allow-host", action="append", default=[], metavar="NAME")
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
    server = web.LocalServer((args.host, args.port), Handler, args.allow_host)
    workers = 0 if inference else parallel.warm()   # in-process boards split too
    print("Countrix: http://%s:%d%s" % (
        args.host, args.port, " (%d solver workers)" % workers if workers else ""))
    server.serve_forever()


if __name__ == "__main__":
    main()
