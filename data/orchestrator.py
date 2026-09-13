"""The conductor: the database's verbs, driven through the data layer's own
tools rather than a chain of subprocesses.

Every verb refuses the state it is not for and names the verb you wanted:

    init      apply the migrations to an empty database - schema, no data
    inflate   the first fill: sync_all into a fresh schema. Refuses a
              database that already holds data - loading again is `update`.
    update    (default) sync_all into a populated database. Entity tables
              refresh in place; each rates pull appends a dated snapshot.
    rebuild   drop everything, reapply the migrations, sync_all, restore
              recorded recommendations from the data/raw mirror.
    export    refresh data/raw/*.csv
    docs      regenerate docs/erd.md, data-dictionary.md, heuristics.md

    python -m data.orchestrator rebuild
    python -m data.orchestrator                       update, everything
    python -m data.orchestrator --only pull_rates     update one tool
    python -m data.orchestrator --refresh             re-fetch instead of caching

The same tools are what a Claude Code session calls over MCP (.mcp.json);
this module exists so Docker, cron and a shell can run them without one.
"""

import sys

import psycopg

from data.common import build_parser, resolve_dsn
from data.db import schema
from data.mcp import tools


def run_tools(args, ctx):
    """sync_all, or the subset named by --only, in dependency order."""
    order = [name for name, _ in tools.PULLS] + ["load_playbook", "export_csv"]
    selected = order
    if args.only:
        unknown = [n for n in args.only if n not in order]
        if unknown:
            sys.exit("error: unknown tool(s): %s\nknown: %s"
                     % (", ".join(unknown), ", ".join(order)))
        selected = [n for n in order if n in args.only]
    for index, name in enumerate(selected, start=1):
        if name == "export_csv" and args.command in ("rebuild", "inflate"):
            # before the mirror is rewritten; a no-op on a populated database
            with ctx.connect() as connection:
                restored = schema.restore_recommendations(connection)
                if restored:
                    print("\nrestored %d recorded-recommendation rows from the"
                          " data/raw mirror" % restored)
        print("\n=== [%d/%d] %s ===" % (index, len(selected), name))
        kwargs = {"refresh": args.refresh} if name in dict(tools.PULLS) else {}
        text, _ = tools.run_tool(ctx, name, **kwargs)
        print(text)
    print("\nall %d tools completed" % len(selected))


def main():
    parser = build_parser(__doc__)
    parser.add_argument(
        "command", nargs="?", default="update",
        choices=("init", "inflate", "update", "rebuild", "export", "docs"))
    parser.add_argument("--only", action="append",
                        help="run just this tool (repeatable): pull_heroes,"
                             " pull_kits, ... load_playbook, export_csv")
    parser.add_argument("--refresh", action="store_true",
                        help="discard page caches and fetch again")
    args = parser.parse_args()
    ctx = tools.Context(dsn=resolve_dsn(args), log=print)

    if args.command == "docs":
        print(tools.run_tool(ctx, "db_docs")[0])
        return
    if args.command == "export":
        print(tools.run_tool(ctx, "export_csv")[0])
        return
    if args.command == "init":
        with psycopg.connect(ctx.dsn) as connection:
            if schema.table_count(connection):
                sys.exit("error: the database already has tables; `rebuild`"
                         " is the verb that starts over")
            schema.apply(connection, schema.read_migrations())
            print("\n%d tables, no data; `inflate` fills them"
                  % schema.table_count(connection))
        return
    if args.command in ("rebuild", "inflate") and args.only:
        sys.exit("error: %s always runs every tool; use update with --only"
                 " for partial runs" % args.command)
    if args.command == "rebuild":
        with psycopg.connect(ctx.dsn) as connection:
            schema.rebuild(connection)
    else:
        with psycopg.connect(ctx.dsn) as connection:
            if schema.table_count(connection) == 0:
                sys.exit("error: the database is empty; run"
                         " `python -m data.orchestrator init` (or rebuild) first")
            if args.command == "inflate" and connection.execute(
                    "SELECT count(*) FROM heroes").fetchone()[0]:
                sys.exit("error: the database already holds data; `update`"
                         " is the verb for loading again")
    run_tools(args, ctx)


if __name__ == "__main__":
    try:
        main()
    except (schema.SchemaError, psycopg.Error) as error:
        sys.exit("error: %s" % error)
