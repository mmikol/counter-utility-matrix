"""python -m door.mcp                        serve the tools over stdio
python -m door.mcp --http [HOST:]PORT [NAME ...]
                                          serve them over Streamable HTTP (/mcp, /health),
                                          answering to the local names and each NAME
python -m door.mcp list                   list the tools
python -m door.mcp call NAME [JSON-ARGS]  run one tool and print its text"""

import json
import sys
from collections.abc import Callable

from db import Refusal, psql
from door.mcp import http, lifecycle, stdio, tools
from door.mcp.server import Server


def _status(ctx: tools.Context) -> Callable[[], dict[str, object]]:
    """The data container's /health: the database's state and counts, or
    degraded with the reason when the database is out of reach. It reads
    the database directly, not through the door - a read writes nothing -
    so a healthcheck leaves no audit line."""
    def status() -> dict[str, object]:
        try:
            found = lifecycle.read_status(ctx)
            return {"status": "ok", "state": found["state"],
                    "table_count": found["table_count"],
                    "pending_migrations": found["pending_migrations"],
                    "heroes": found["counts"].get("heroes", 0),
                    "announced": found["counts"].get("announced", 0),
                    "newest_capture": found["newest_capture"]}
        except psql.UNREACHABLE as error:     # the server is up even if the DB is not
            return {"status": "degraded", "error": str(error)}
    return status


def _call(ctx: tools.Context, name: str, text: str) -> int:
    """`call NAME [JSON-ARGS]`: the tool's text on stdout -> 0; its refusal,
    or a name no tool has, on stderr -> 1; arguments that are not one JSON
    object, the usage on stderr -> 2. Anything else is raised with its
    traceback: a fault inside a tool is not the caller's to fix."""
    try:
        arguments = json.loads(text)
    except json.JSONDecodeError:
        arguments = None
    if not isinstance(arguments, dict):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        shown, _ = ctx.call(name, **arguments)
    except (tools.NoSuchToolError, Refusal) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    print(shown)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ctx = tools.Context(client="shell")
    server = Server(tools.REGISTRY.bind(ctx), tools.StrategyResources())
    if not argv:
        stdio.serve(server)
        return 0
    if argv[0] == "--http" and len(argv) >= 2:
        host, _, port = argv[1].rpartition(":")
        http.serve(server, host or "127.0.0.1", int(port), _status(ctx),
                   allowed_hosts=argv[2:])
        return 0
    if argv[0] == "list":
        for t in tools.REGISTRY.bind(ctx):
            print("%-16s %s" % (t.name, t.description.split(". ")[0]))
        return 0
    if argv[0] == "call" and len(argv) >= 2:
        return _call(ctx, argv[1], argv[2] if len(argv) > 2 else "{}")
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
