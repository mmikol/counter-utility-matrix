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
the traceback on stderr. A service behind the board - the inference service,
the MCP door - that fails or does not answer is a 502, by db.web's relay
map. Every board solved, and every request that fails, leaves a line on
stderr.
"""

import argparse
import json
import os
import sys
import urllib.request
from collections.abc import Mapping, Sequence
from urllib.parse import parse_qs, urlencode, urlsplit

import psycopg
from psycopg.rows import TupleRow

from db import psql, web
from door.mcp import tools
from facts import board_facts, tables
from facts.draft import Query, parse_board
from facts.roster import roster_of
from inference import catalog as catalog_module
from inference import parallel, serve
from inference.strategy import finite_number
from ui import pages

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


# The inference service's handlers (inference/serve.py) run in-process unless
# a service is named: in the compose stack the `inference` container serves them.
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
    """Forward to the inference service -> its reply, by db.web's relay map:
    its 200, 400 (the query went as received) or 429 as it answered, any
    other status 502 with its body, so a crash on the service reads 502. A
    service that does not answer is a 502 and a line on stderr naming why;
    one that answers with no JSON object is a 502 too."""
    url = inference_url() + path
    if query:
        url += "?" + urlencode(query, doseq=True)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        answer = web.read_json(request, REMOTE_TIMEOUT)
    except OSError as error:
        sys.stderr.write(
            "countrix board: the inference service at %s did not answer %s: %s\n"
            % (inference_url(), path, error))
        return web.Reply({"error": "inference service unreachable: %s" % error}, 502)
    if not isinstance(answer.body, dict):
        said = "the inference service answered %d with no JSON object" % answer.status
        return web.Reply({"error": said}, 502)
    return web.Reply(answer.body, answer.status if answer.status in (200, 400, 429) else 502)


# --- JSON endpoints ---------------------------------------------------------

def api_roster(cx: psycopg.Connection[TupleRow]) -> web.Reply:
    """The roster the door's roster tool lists, with the role icons and the
    patches newer than the rates the page draws beside it."""
    world = tables.load(cx)
    listed = roster_of(world)
    return web.Reply({"heroes": listed["heroes"], "maps": listed["maps"],
                      "role_icons": world.role_icons,
                      "newer_patches": world.newer_patches}, 200)


def api_facts(cx: psycopg.Connection[TupleRow], query: Query) -> web.Reply:
    draft = parse_board(query)
    world = tables.load(cx)
    return web.Reply(board_facts.generate(world, draft).to_dict(), 200)


def api_board(query: Query) -> web.Reply:
    """The board solved at this stage of the draft: on the service when one
    is named, else serve.handle_board in this process, the one branch that
    opens a connection. The query goes as received - the playbook tab's
    weights and the page's client with it - and the service's parse refuses
    anything malformed."""
    if inference_url():
        return remote("/board", query)
    with psycopg.connect(psql.default_dsn()) as cx:
        return serve.handle_board(cx, query)


def tool_context() -> tools.Context:
    """Where an in-process tool call lands: the database default_dsn() names,
    the call audited as the board's."""
    return tools.Context(client="board")


def api_weight(payload: Mapping[str, object] | None) -> web.Reply:
    """Store a heuristic's weight in its file - the slider's "store". The
    change goes through the `tune` tool (validated, logged in the tuning
    log with its reason, mirrored into the database), never around it, and
    tune holds the range; a malformed id or a weight that is not a number
    never reaches it. Over HTTP the call's status is relayed by
    db.web's map - the tool's refusal 400, the door's 429 as it came, any
    other failure 502; in-process a refusal is raised and the POST's
    boundary answers it 400, so it reads the same on both paths. A crash
    inside tune reads 500 in-process and 502 remote."""
    payload = payload or {}
    strategy_id = str(payload.get("id") or "")
    if not catalog_module.ID_RE.fullmatch(strategy_id):
        return web.Reply({"error": "no such heuristic"}, 400)
    number = finite_number(payload.get("weight"))
    if number is None:
        return web.Reply({"error": "the weight must be a number"}, 400)
    weight = round(number, 2)
    arguments = {
        "id": strategy_id, "field": "weight", "value": weight, "reason": STORE_REASON,
        "by": "the board"}
    if mcp_url():
        reply = web.call_tool(mcp_url(), "tune", arguments, token=mcp_token())
        if reply.is_error:
            return web.Reply({"error": reply.text}, reply.status)
        return web.Reply({"line": reply.text.split("\n")[0], "change": reply.structured}, 200)
    text, stored = tool_context().call("tune", **arguments)
    return web.Reply({"line": text.split("\n")[0], "change": stored}, 200)


def api_strategies() -> web.Reply:
    """The catalog: the service's when one is named, else
    serve.handle_strategies in this process."""
    return remote("/strategies") if inference_url() else serve.handle_strategies()


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
