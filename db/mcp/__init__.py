"""The door over all three layers: an MCP server whose tools are the data
layer's pulls - every source fetched, cleaned and stored in Postgres - and
the tools the UI and inference layers expose through it: the facts, the
solver and the playbook. Every write to Postgres or the playbook runs under
one of them, the sentry's quarantine rename aside.

    python -m db.mcp                 serve over stdio (what .mcp.json launches)
    python -m db.mcp --http H:PORT   serve over HTTP (the data container)
    python -m db.mcp list            print the tools
    python -m db.mcp call pull_maps  run one tool from the shell

    server       the protocol: JSON-RPC over stdio and Streamable HTTP, the
                 schema check every call passes, the audit line it leaves
    registry     what a tool is, the Registry a family of tools is declared
                 into, and the Context a call lands in
    tools        the families joined in the order the server lists them, and
                 the Context the servers, the refresher and the board use
    pulls        pull, clean, store: the pull_* tools, load_authored, sync_all
    lifecycle    the database's life: status, init, migrate, rebuild, the CSV
                 mirror, the generated docs, read-only query
    layers       the UI and inference layers: roster, facts, infer, evaluate,
                 reach, board, metrics
    playbook     the strategies and the tools that write them, the tuning
                 log, the strategy:// resources
    __main__     the command line above

The protocol implementation is dependency-free (server.py) so the door has
nothing to audit but its own few hundred lines; the surface is the standard
one - initialize, tools/list, tools/call, resources - so any MCP client can
drive it.
"""
