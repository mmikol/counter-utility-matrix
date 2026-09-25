"""The door over all three layers: an MCP server whose tools are the data
layer's pulls - every source fetched, cleaned and stored in Postgres - and
the tools the facts and inference layers expose through it: the facts, the
solver and the playbook, and the owner's recorded matches. Every write to
Postgres or the playbook runs under one of them, the sentry's quarantine
rename aside.

    .venv/bin/python -m door.mcp                  serve over stdio (what .mcp.json launches)
    python -m door.mcp --http H:PORT              serve over HTTP (the data container)
    .venv/bin/python -m door.mcp list             print the tools
    .venv/bin/python -m door.mcp call pull_maps   run one tool from the shell

    server       the protocol: JSON-RPC answered from a server's tools and
                 resources, whichever transport carries it
    stdio        the stdio transport, one message a line
    http         the Streamable HTTP transport, and the bearer token, the
                 caps and the rate limit a client is held to
    schema       a tool as the protocol serves it: its arguments as JSON
                 Schema, its reply, and the Tool that checks every call
    audit        the audit line every call leaves, through any door
    registry     the one Registry every family declares its tools into, the
                 order it lists the families in, and the Context a call
                 lands in
    tools        every family imported, so the registry is whole, and the
                 Context the servers, the refresher and the board use
    pulls        pull, clean, store: the pull_* tools, load_authored, sync_all
    lifecycle    the database's life: status, init, migrate, rebuild, the CSV
                 mirror, the generated docs, read-only query
    boards       the five properties a board tool takes, and board_tool,
                 which hands its function the one Draft they name
    facts        the facts layer: roster and a board's facts
    solver       the inference layer: infer, evaluate, reach, board, and
                 validate_playbook, the playbook against the recorded matches
    playbook     the metric vocabulary, the strategies and the tools that
                 write them, the tuning log, the strategy:// resources
    matches      the owner's recorded matches: record_match, which checks a
                 played map before it stores it, list_matches, delete_match
    __main__     the command line above

The protocol and its transports are dependency-free (server, stdio, http,
schema, audit), so the door has nothing to audit but its own few hundred
lines; the surface is the standard one - initialize, tools/list,
tools/call, resources - so any MCP client can drive it.
"""
