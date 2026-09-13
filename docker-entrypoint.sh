#!/bin/sh
# First run: build the database (migrations + every pipeline - scrapes the
# sources once; the mounted caches make later builds cheap). Every run after:
# serve the UI. Any explicit command bypasses this:
#   docker compose run app python -m orchestrator update
#   docker compose run app pytest -q
set -e
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

tables=$(python - <<'PY'
import os, time, psycopg
for _ in range(30):
    try:
        cx = psycopg.connect(os.environ["DATABASE_URL"])
        break
    except psycopg.Error:
        time.sleep(1)
else:
    raise SystemExit("database service never became reachable")
print(cx.execute("select count(*) from pg_tables where schemaname='public'")
      .fetchone()[0])
PY
)
if [ "$tables" = "0" ]; then
    echo "empty database: running the first build (scrapes the sources once)"
    python -m orchestrator rebuild
fi
exec python ui.py
