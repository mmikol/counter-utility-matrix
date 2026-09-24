"""python -m db.mcp                       serve the data layer over stdio
python -m db.mcp --http [HOST:]PORT     serve it over Streamable HTTP (/mcp, /health)
python -m db.mcp list                   list the tools
python -m db.mcp call NAME [JSON-ARGS]  run one tool and print its text"""

import json
import sys
from collections.abc import Callable

from db import Refusal, psql
from db.mcp import tools
from db.mcp.server import Server, serve_http


def _status(ctx: tools.Context) -> Callable[[], dict[str, object]]:
    """The data container's /health: the database's state and counts, or
    degraded with the reason when the database is out of reach."""
    def status() -> dict[str, object]:
        try:
            _, data = tools.run_tool(ctx, "db_status")
            return {"status": "ok", "state": data["state"],
                    "table_count": data["table_count"],
                    "pending_migrations": data["pending_migrations"],
                    "heroes": data["counts"].get("heroes", 0),
                    "announced": data["counts"].get("announced", 0),
                    "newest_capture": data.get("newest_capture")}
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
        shown, _ = tools.run_tool(ctx, name, **arguments)
    except (tools.NoSuchToolError, Refusal) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    print(shown)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ctx = tools.Context()
    server = Server(tools.build(ctx), tools.StrategyResources())
    if not argv:
        server.serve()
        return 0
    if argv[0] == "--http" and len(argv) >= 2:
        host, _, port = argv[1].rpartition(":")
        serve_http(server, host or "127.0.0.1", int(port), _status(ctx),
                   allowed_hosts=argv[2:])
        return 0
    if argv[0] == "list":
        for t in tools.build(ctx):
            print("%-16s %s" % (t.name, t.description.split(". ")[0]))
        return 0
    if argv[0] == "call" and len(argv) >= 2:
        return _call(ctx, argv[1], argv[2] if len(argv) > 2 else "{}")
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
