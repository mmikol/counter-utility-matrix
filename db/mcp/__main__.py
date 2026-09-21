"""python -m db.mcp                       serve the data layer over stdio
python -m db.mcp --http [HOST:]PORT     serve it over Streamable HTTP (/mcp, /health)
python -m db.mcp list                   list the tools
python -m db.mcp call NAME [JSON-ARGS]  run one tool and print its text"""

import json
import sys

from db.mcp import tools
from db.mcp.server import Server, ToolError, serve_http


def _status(ctx):
    def status():
        try:
            _, data = tools.run_tool(ctx, "db_status")
            return {"status": "ok", "table_count": data["table_count"],
                    "pending_migrations": data["pending_migrations"],
                    "heroes": data["counts"].get("heroes", 0),
                    "announced": data["counts"].get("announced", 0),
                    "newest_capture": data.get("newest_capture")}
        except Exception as error:      # the server is up even if the DB is not
            return {"status": "degraded", "error": str(error)}
    return status


def main(argv=None):
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
        arguments = json.loads(argv[2]) if len(argv) > 2 else {}
        try:
            text, _ = tools.run_tool(ctx, argv[1], **arguments)
        except (ToolError, KeyError) as error:
            sys.exit("error: %s" % error)
        print(text)
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
