"""The inference engine as a service: the container the board talks to.

    python -m inference.serve --port 8019

    GET  /health                       the catalog size and the database state
    GET  /board?map=&side=&red=&blue=&bans=   both seats' optimal six + the current comp
    GET  /infer?map=&side=&red=&blue=&bans=[&top=&pool=]   blue's optimal six
    GET  /evaluate?map=&side=&red=&blue=&bans=   a full six scored against the field
    GET  /strategies                   the catalog

The same functions ui/board.py calls in-process when no INFERENCE_URL is set.
http.server, no web framework.
"""

import argparse
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import psycopg

from db import psql
from inference import catalog as catalog_module
from inference import engine
from ui.facts import model
from ui.facts.compute import parse_board

PORT = int(os.environ.get("COUNTRIX_INFERENCE_PORT", "8019"))

# A parsed query string, and a handler's answer: a JSON object and its status.
Query = dict[str, list[str]]
Answer = tuple[dict[str, Any], int]


def _first(query: Query, key: str) -> str | None:
    """A parameter's first value, or None when the query leaves it out."""
    values = query.get(key)
    return values[0] if values else None


def handle_infer(cx: psycopg.Connection, query: Query) -> Answer:
    """Blue's optimal six around its locked picks, at any stage of the draft.
    Ranking a full six against the field is /evaluate's question, so this door
    infers whatever blue holds and honours the `top` it was given. The MCP tool
    of the same name draws the line in the same place."""
    map_name, red, blue, bans, side = parse_board(query)
    world = model.load(cx)
    try:
        pool, top = engine.clamp_search(_first(query, "pool"),
                                        _first(query, "top"))
        result = engine.infer(world, map_name, red, blue, bans=bans, side=side,
                              pool_size=pool, top=top)
    except ValueError as error:
        return {"error": str(error)}, 400
    return result.to_dict(), 200


def handle_evaluate(cx: psycopg.Connection, query: Query) -> Answer:
    map_name, red, blue, bans, side = parse_board(query)
    world = model.load(cx)
    try:
        result = engine.evaluate(world, map_name, red, blue, bans=bans, side=side)
    except ValueError as error:
        return {"error": str(error)}, 400
    return result.to_dict(), 200


def handle_board(cx: psycopg.Connection, query: Query) -> Answer:
    """Both seats and the current comp - what the board's two displays show."""
    map_name, red, blue, bans, side = parse_board(query)
    weights = catalog_module.parse_weights(query.get("weights", []))
    world = model.load(cx)
    try:
        pool, _ = engine.clamp_search(_first(query, "pool"))
        b = engine.board(world, map_name, red, blue, bans, side, pool_size=pool,
                         weights=weights)
    except ValueError as error:
        return {"error": str(error)}, 400
    return b.to_dict(), 200


def handle_strategies() -> Answer:
    return {"strategies": [h.to_dict() for h in catalog_module.load()],
            "playbook": catalog_module.playbook_name()}, 200


def handle_health() -> Answer:
    cat = catalog_module.load()
    out: dict[str, Any] = {"status": "ok", "strategies": len(cat),
                           "pending": sum(1 for h in cat if h.pending)}
    # Degraded is the answer to every way the database can be out of reach,
    # and finding it is one of them: default_dsn imports pgserver to locate
    # the embedded cluster, so a machine without that package raised
    # ModuleNotFoundError out of a handler whose whole job is to say what is
    # wrong. A health endpoint that crashes reports nothing.
    try:
        with psycopg.connect(psql.default_dsn()) as cx:
            out["heroes"] = psql.scalar(cx.execute("select count(*) from heroes"))
    except psql.UNREACHABLE as error:
        out["status"], out["error"] = "degraded", str(error)
    return out, 200


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _json(self, payload: object, code: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/health":
                return self._json(*handle_health())
            if path == "/strategies":
                return self._json(*handle_strategies())
            if path not in ("/board", "/infer", "/evaluate"):
                return self._json({"error": "nothing here"}, 404)
            with psycopg.connect(psql.default_dsn()) as cx:   # only these routes connect
                if path == "/board":
                    return self._json(*handle_board(cx, query))
                if path == "/infer":
                    return self._json(*handle_infer(cx, query))
                return self._json(*handle_evaluate(cx, query))
        except Exception:
            self._json({"error": traceback.format_exc()}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("COUNTRIX_INFERENCE_HOST",
                                                         "127.0.0.1"))
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    workers = engine.warm()                    # the board's solves split across these
    print("countrix inference: http://%s:%d%s" % (
        args.host, args.port, " (%d solver workers)" % workers if workers else ""))
    server.serve_forever()


if __name__ == "__main__":
    main()
