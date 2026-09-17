#!/bin/sh
# One image, one container per layer. The first argument is the role:
#
#   data        DATA LAYER: build the database when it is empty or its
#               schema is behind the migrations (scrapes the sources once;
#               the mounted caches make later builds cheap), then serve the
#               MCP server over HTTP on 8020
#   inference   INFERENCE ENGINE: wait for the database, serve on 8019
#   ui          UI LAYER: wait for the database, serve the board on 8017
#   refresh     DATA LAYER's clock: wait for the database, then refresh it
#               daily (db/refresh.py)
#   sentry      the guard: the playbook, the inputs and the door, every
#               COUNTER_MATRIX_SENTRY_EVERY seconds (db/sentry.py)
#
# Anything else is run as a command in the image:
#   docker compose run data python -m db.mcp call sync_all
#   docker compose run data pytest -q
set -e
role="${1:-ui}"
case "$role" in
    data|inference|ui|refresh|sentry) ;;
    *) exec "$@" ;;
esac

db_state() {
    python - <<'END'
import os, sys, time, psycopg
from db.psql import schema
for _ in range(60):
    try:
        cx = psycopg.connect(os.environ["DATABASE_URL"])
        break
    except psycopg.Error:
        time.sleep(1)
else:
    raise SystemExit("database service never became reachable")
if schema.table_count(cx) == 0:
    print("empty")
elif schema.pending(cx):
    print("stale: " + ", ".join(schema.pending(cx)))
elif cx.execute("select count(*) from heroes").fetchone()[0] == 0:
    print("unfilled")
else:
    print("current")
END
}

case "$role" in
    sentry)
        exec python -m db.sentry ;;
    data)
        state=$(db_state)
        case "$state" in
            empty|unfilled)
                echo "data: $state database - running the first build (scrapes the sources once)"
                python -m db.mcp call db_rebuild ;;
            stale*)
                echo "data: schema behind the migrations ($state) - rebuilding from the caches"
                python -m db.mcp call db_rebuild ;;
            *)
                echo "data: database current" ;;
        esac
        exec python -m db.mcp --http 0.0.0.0:8020 data ;;
    inference|ui|refresh)
        until [ "$(db_state)" = "current" ]; do
            echo "$role: waiting for the data layer to build the database"
            sleep 10
        done
        case "$role" in
            inference) exec python -m inference.serve --host 0.0.0.0 --port 8019 ;;
            refresh)   exec python -m db.refresh ;;
            *)         exec python -m ui.board --host 0.0.0.0 --port 8017 ;;
        esac ;;
esac
