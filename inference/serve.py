"""The inference engine as a service: the container the board talks to.

    python -m inference.serve --port 8019

    GET  /health                       the catalog size and the database state
    GET  /infer?map=&red=&blue=&ban=[&top=&pool=]   the optimal six
    GET  /evaluate?map=&red=&blue=&ban=     a full six scored against the field
    GET  /heuristics                   the catalog
    POST /record  {question, map, red, blue, model, answer}   the gates + tables

The same functions user/board.py calls in-process when no INFERENCE_URL is set;
standard library only.
"""

import argparse
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import psycopg

from data import common
from user.facts import model
from user.facts.compute import TEAM_SIZE
from inference import catalog as catalog_module
from inference import engine
from inference import record as record_module

PORT = int(os.environ.get("OVERWATCH_DB_INFERENCE_PORT", "8019"))


def board(query):
    map_name = (query.get("map") or [None])[0] or None
    red = [x for x in query.get("red", []) if x]
    blue = [x for x in query.get("blue", []) if x]
    bans = [x for x in query.get("ban", []) if x][:5]
    return map_name, red, blue, bans


def handle_infer(cx, query):
    map_name, red, blue, bans = board(query)
    top = int((query.get("top") or ["5"])[0])
    pool = int((query.get("pool") or ["6"])[0])
    world = model.load(cx)
    try:
        if len(blue) == TEAM_SIZE:
            result = engine.evaluate(world, map_name, red, blue, pool_size=pool, bans=bans)
        else:
            result = engine.infer(world, map_name, red, blue, top=top, pool_size=pool,
                                  bans=bans)
    except ValueError as error:
        return {"error": str(error)}, 400
    return result.to_dict(), 200


def handle_evaluate(cx, query):
    map_name, red, blue, bans = board(query)
    world = model.load(cx)
    try:
        result = engine.evaluate(world, map_name, red, blue, bans=bans)
    except ValueError as error:
        return {"error": str(error)}, 400
    return result.to_dict(), 200


def handle_heuristics():
    return {"heuristics": [h.to_dict() for h in catalog_module.load()]}, 200


def handle_record(cx, payload):
    try:
        rec_id, path = record_module.record(
            cx, payload.get("question") or "recorded through the inference service",
            payload["answer"], payload.get("map"), payload.get("red", []),
            payload.get("blue", []), payload.get("model", "inference-service"),
            payload.get("bans", []))
    except (ValueError, KeyError) as error:
        return {"error": str(error)}, 400
    return {"rec_id": rec_id, "transcript": os.path.relpath(path, common.ROOT)}, 200


def handle_health():
    out = {"status": "ok", "heuristics": len(catalog_module.load())}
    try:
        with psycopg.connect(common.default_dsn()) as cx:
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
            if path == "/heuristics":
                return self._json(*handle_heuristics())
            with psycopg.connect(common.default_dsn()) as cx:
                if path == "/infer":
                    return self._json(*handle_infer(cx, query))
                if path == "/evaluate":
                    return self._json(*handle_evaluate(cx, query))
            self._json({"error": "nothing here"}, 404)
        except Exception:
            self._json({"error": traceback.format_exc()}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if parsed.path == "/record":
                with psycopg.connect(common.default_dsn()) as cx:
                    return self._json(*handle_record(cx, payload))
            self._json({"error": "nothing here"}, 404)
        except Exception as error:
            self._json({"error": str(error)}, 500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("OVERWATCH_DB_INFERENCE_HOST",
                                                         "127.0.0.1"))
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print("overwatch-db inference: http://%s:%d" % (args.host, args.port))
    server.serve_forever()


if __name__ == "__main__":
    main()
