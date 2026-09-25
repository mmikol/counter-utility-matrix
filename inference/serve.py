"""The inference engine as a service: the container the board talks to.

    python -m inference.serve --port 8019 [--allow-host NAME ...]

    GET  /health                       the catalog size and the database state; 200
                                       and degraded, naming why, when either is out
                                       of reach
    GET  /board?map=&side=&red=&blue=&bans=[&weights=&client=&pool=]   both seats' optimal
                                       six + the current comp, under the playbook
                                       tab's weights; a newer board from the same
                                       client supersedes one still solving
    GET  /infer?map=&side=&red=&blue=&bans=[&top=&pool=]   blue's optimal six
    GET  /evaluate?map=&side=&red=&blue=&bans=   a full six scored against the field
    GET  /strategies                   the catalog

ui/board.py calls handle_board and handle_strategies in-process when
COUNTRIX_INFERENCE_URL is unset. http.server on db.web's server and
handler, no web framework: a request whose Host or Origin names another
server is refused with 403 - --allow-host adds the names it is called by,
as `inference` in the compose stack - and every solve leaves a line on
stderr with how long it took. A request that raises is answered by
db.web.failure: a Refusal 400 with its message, anything else 500 with its
type and message, the traceback on stderr.
"""

import argparse
import os
from typing import Literal, NotRequired, TypedDict
from urllib.parse import parse_qs, urlsplit

import psycopg

from db import psql, web
from facts import tables
from facts.draft import Query, parse_board
from inference import catalog as catalog_module
from inference import engine, parallel, supersede
from inference.strategy import CatalogError

SOLVES = ("/board", "/infer", "/evaluate")     # the routes that search, and connect


class Health(TypedDict):
    """What /health answers: ok or degraded; the strategy counts where the
    playbook loads; the heroes where the database answers; and the error,
    naming each thing out of reach, where either does not."""
    status: Literal["ok", "degraded"]
    strategies: NotRequired[int]
    pending: NotRequired[int]
    heroes: NotRequired[int]
    error: NotRequired[str]


def _first(query: Query, key: str) -> str | None:
    """A parameter's first value, or None when the query leaves it out."""
    values = query.get(key)
    return values[0] if values else None


def handle_infer(cx: psycopg.Connection, query: Query) -> web.Reply:
    """Blue's optimal six around its locked picks, at any stage of the draft.
    Ranking a full six against the field is /evaluate's question, so this door
    infers whatever blue holds and honours the `top` it was given. The MCP tool
    of the same name draws the line in the same place."""
    draft = parse_board(query)
    world = tables.load(cx)
    pool, top = engine.clamp_search(_first(query, "pool"), _first(query, "top"))
    return web.Reply(engine.infer(world, draft, pool_size=pool, top=top).to_dict(), 200)


def handle_evaluate(cx: psycopg.Connection, query: Query) -> web.Reply:
    """Blue's full six scored and ranked against the field."""
    draft = parse_board(query)
    world = tables.load(cx)
    return web.Reply(engine.evaluate(world, draft).to_dict(), 200)


def handle_board(cx: psycopg.Connection, query: Query) -> web.Reply:
    """Both seats and the current comp - what the board's two displays show -
    under the playbook tab's weights. The page never reads the countered case,
    so it is not solved here; a newer board from the same `client` (one lane
    when none is named) supersedes this one, which then answers 400. The whole
    query is read before the lane is taken, so a malformed one supersedes
    nothing."""
    draft = parse_board(query)
    weights = catalog_module.parse_weights(query.get("weights", []))
    pool, _ = engine.clamp_search(_first(query, "pool"))
    superseded = supersede.LATEST.take(_first(query, "client") or "")
    world = tables.load(cx)
    brief = engine.Brief(pool_size=pool, weights=weights, countered=False, superseded=superseded)
    return web.Reply(engine.board(world, draft, brief=brief).to_dict(), 200)


def handle_strategies() -> web.Reply:
    """The catalog. A playbook that does not load is the server's fault: the
    CatalogError reaches the request boundary, a 500."""
    return web.Reply({"strategies": [h.to_dict() for h in catalog_module.load()],
                      "playbook": catalog_module.playbook_name()}, 200)


def handle_health() -> web.Reply:
    """The catalog's size and the database's state, always 200: a playbook
    that does not load leaves the strategy counts out, and it or a database
    out of reach makes the status degraded, the error naming each - what
    orchestrator.py prints while it waits."""
    out: Health = {"status": "ok"}
    errors: list[str] = []
    try:
        cat = catalog_module.load()
    except CatalogError as error:
        errors.append(str(error))
    else:
        out["strategies"], out["pending"] = len(cat), sum(1 for h in cat if h.pending)
    # psql.UNREACHABLE: a database out of reach is degraded, never a 500
    try:
        with psycopg.connect(psql.default_dsn()) as cx:
            out["heroes"] = psql.scalar(cx.execute("select count(*) from heroes"))
    except psql.UNREACHABLE as error:
        errors.append(str(error))
    if errors:
        out["status"], out["error"] = "degraded", "; ".join(errors)
    return web.Reply(dict(out), 200)


class Handler(web.Handler):
    timed = frozenset(SOLVES)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/health":
                return self._json(*handle_health())
            if path == "/strategies":
                return self._json(*handle_strategies())
            if path not in SOLVES:
                return self._json({"error": "nothing here"}, 404)
            with psycopg.connect(psql.default_dsn()) as cx:   # only the solves connect
                if path == "/board":
                    return self._json(*handle_board(cx, query))
                if path == "/infer":
                    return self._json(*handle_infer(cx, query))
                return self._json(*handle_evaluate(cx, query))
        except Exception as error:  # noqa: BLE001  # the request boundary
            self._json(*web.failure(error))


def command_line(argv: list[str] | None = None) -> argparse.Namespace:
    """The command line. Where the service listens defaults to
    COUNTRIX_INFERENCE_HOST and COUNTRIX_INFERENCE_PORT, both read when it
    starts; --allow-host, repeated, names a host it answers to beside the
    local ones."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("COUNTRIX_INFERENCE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("COUNTRIX_INFERENCE_PORT", "8019")))
    parser.add_argument("--allow-host", action="append", default=[], metavar="NAME")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Serve the engine until interrupted, its pool warmed first."""
    args = command_line(argv)
    server = web.LocalServer((args.host, args.port), Handler, args.allow_host)
    workers = parallel.warm()                    # the board's solves split across these
    print("countrix inference: http://%s:%d%s" % (
        args.host, args.port, " (%d solver workers)" % workers if workers else ""))
    server.serve_forever()


if __name__ == "__main__":
    main()
