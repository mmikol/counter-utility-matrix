"""The DOOR over all three layers: the MCP tools every write runs under, the
clock that runs them on a schedule, and the guard that watches the playbook
beside the database.

The door gates every write to Postgres and the playbook, the sentry's
quarantine rename aside. The code that writes lives with what it writes -
the pulls in db.data, inference.catalog.mirror, which reloads the strategies
table, and inference.tune, which edits the playbook's files - and is called
only from a door tool, or from inference.derive inside a run the door
started. Reads bypass the door: the facts and inference layers connect
through db.psql.default_dsn(). The door imports db, facts and inference,
and none of them imports it.

    mcp/        the MCP server and its tools, the one door, for a session,
                the refresher, Docker's entrypoint and the shell alike
                (`.venv/bin/python -m door.mcp call <tool>`)
    refresh     the door's clock: the daily refresh, and the full one once
                the wiki cache is a week old, run through the door's tools
    sentry      the guard over the playbook, the database's free text and
                the door's audit log
"""
