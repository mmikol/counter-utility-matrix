"""The inference engine as a service: the container the board talks to.

    python -m inference.serve --port 8019

    GET  /health                       the catalog size and the database state
    GET  /board?map=&side=&red=&blue=&ban=   both seats' optimal six + the current comp
    GET  /infer?map=&side=&red=&blue=&ban=[&top=&pool=]   blue's optimal six
    GET  /evaluate?map=&side=&red=&blue=&ban=   a full six scored against the field
    GET  /strategies                   the catalog

The same functions ui/board.py calls in-process when no INFERENCE_URL is set.
http.server, no web framework.
"""

import argparse
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import psycopg

from db import psql
from inference import catalog as catalog_module
from inference import engine
from ui.facts import model
from ui.facts.compute import MAX_BANS, TEAM_SIZE

PORT = int(os.environ.get("COUNTER_MATRIX_INFERENCE_PORT", "8019"))


def parse_board(query):
    """The board a query names: (map, red, blue, bans, side)."""
    map_name = (query.get("map") or [None])[0] or None
    red = [x for x in query.get("red", []) if x]
    blue = [x for x in query.get("blue", []) if x]
    bans = [x for x in query.get("ban", []) if x][:MAX_BANS]
    side = (query.get("side") or [""])[0]
    return map_name, red, blue, bans, side


def handle_infer(cx, query):
    map_name, red, blue, bans, side = parse_board(query)
    top = int((query.get("top") or ["5"])[0])
    pool = int((query.get("pool") or ["6"])[0])
    world = model.load(cx)
    try:
        if len(blue) == TEAM_SIZE:
            result = engine.evaluate(world, map_name, red, blue, pool_size=pool, bans=bans,
                                     side=side)
        else:
            result = engine.infer(world, map_name, red, blue, top=top, pool_size=pool,
                                  bans=bans, side=side)
    except ValueError as error:
        return {"error": str(error)}, 400
    return result.to_dict(), 200


def handle_evaluate(cx, query):
    map_name, red, blue, bans, side = parse_board(query)
    world = model.load(cx)
    try:
        result = engine.evaluate(world, map_name, red, blue, bans=bans, side=side)
    except ValueError as error:
        return {"error": str(error)}, 400
    return result.to_dict(), 200


def handle_board(cx, query):
    """Both seats and the current comp - what the board's two displays show."""
    map_name, red, blue, bans, side = parse_board(query)
    pool = int((query.get("pool") or ["6"])[0])
    weights = catalog_module.parse_weights(query.get("weight", []))
    world = model.load(cx)
    try:
        b = engine.board(world, map_name, red, blue, bans, side, pool_size=pool,
                         weights=weights)
    except ValueError as error:
        return {"error": str(error)}, 400
    return engine.board_dict(b), 200


def handle_strategies():
    return {"strategies": [h.to_dict() for h in catalog_module.load()],
            "playbook": catalog_module.playbook_name()}, 200


def handle_health():
    cat = catalog_module.load()
    out = {"status": "ok", "strategies": len(cat), "pending": sum(1 for h in cat if h.pending)}
    try:
        with psycopg.connect(psql.default_dsn()) as cx:
            out["heroes"] = cx.execute("select count(*) from heroes").fetchone()[0]
    except psycopg.Error as error:
        out["status"], out["error"] = "degraded", str(error)
    return out, 200


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, payload, code=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("COUNTER_MATRIX_INFERENCE_HOST",
                                                         "127.0.0.1"))
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    workers = engine.warm()                    # the board's solves split across these
    print("counter-utility-matrix inference: http://%s:%d%s" % (
        args.host, args.port, " (%d solver workers)" % workers if workers else ""))
    server.serve_forever()


if __name__ == "__main__":
    main()
