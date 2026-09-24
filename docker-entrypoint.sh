#!/bin/sh
# One image, one container per layer. The first argument is the role:
#
#   data        DATA LAYER: build the database when it is empty, unfilled or
#               behind the migrations (the first build scrapes the sources;
#               the mounted caches make later builds cheap), then serve the
#               MCP server on 8020
#   inference   INFERENCE ENGINE: wait for the database, serve on 8019
#   ui          UI LAYER: wait for the database, serve the board on 8017
#   refresh     DATA LAYER's clock: wait for the database, then refresh it
#               daily (door/refresh.py)
#   sentry      the guard: the playbook, the database's text and the door, every
#               COUNTRIX_SENTRY_EVERY seconds (door/sentry.py)
#
# Anything else is run as a command in the image:
#   docker compose run data python -m door.mcp call sync_all
#   docker compose run data pytest -q
set -e
role="${1:-ui}"
case "$role" in
    data|inference|ui|refresh|sentry) ;;
    *) exec "$@" ;;
esac

# empty, stale, unfilled or current: db.psql.schema.state, the one definition
# of ready. It waits a minute for the database to answer, then exits 1.
db_state() {
    python -m db.psql.schema
}

case "$role" in
    sentry)
        exec python -m door.sentry ;;
    data)
        state=$(db_state)
        case "$state" in
            empty|unfilled)
                echo "data: $state database - running the first build (scrapes the sources once)"
                python -m door.mcp call db_rebuild ;;
            stale)
                echo "data: schema behind the migrations - rebuilding from the caches"
                python -m door.mcp call db_rebuild ;;
            *)
                echo "data: database current" ;;
        esac
        exec python -m door.mcp --http 0.0.0.0:8020 data ;;
    inference|ui|refresh)
        # as long as the data healthcheck's start_period: 90 waits of 10 s. The
        # probe runs as its own command, so set -e ends the container when it fails
        waits=0
        while :; do
            state=$(db_state)
            [ "$state" = "current" ] && break
            if [ "$waits" -ge 90 ]; then
                echo "$role: the database is still $state after 900 s - giving up" >&2
                exit 1
            fi
            echo "$role: waiting for the data layer to build the database ($state)"
            waits=$((waits + 1))
            sleep 10
        done
        case "$role" in
            # the board calls the service as http://inference:8019 (compose.yaml)
            inference) exec python -m inference.serve --host 0.0.0.0 --port 8019 --allow-host inference ;;
            refresh)   exec python -m door.refresh ;;
            *)         exec python -m ui.board --host 0.0.0.0 --port 8017 ;;
        esac ;;
esac
