"""The DATA LAYER: an MCP server that pulls every source, cleans it, and
stores it in Postgres - plus the board tools the other two layers expose
through the same door.

    python -m db.mcp                 serve over stdio (what .mcp.json launches)
    python -m db.mcp --http H:PORT   serve over HTTP (the data container)
    python -m db.mcp list            print the tools
    python -m db.mcp call pull_maps  run one tool from the shell

The protocol implementation is dependency-free (server.py) so the door has
nothing to audit but its own few hundred lines; the surface is the standard
one - initialize, tools/list, tools/call, resources - so any MCP client can
drive it.
"""
