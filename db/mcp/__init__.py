"""The DATA LAYER: an MCP server that pulls every source, cleans it, and
stores it in Postgres - plus the board tools the other two layers expose
through the same door.

    python -m db.mcp                 serve over stdio (what .mcp.json launches)
    python -m db.mcp list            print the tools
    python -m db.mcp call pull_maps  run one tool from the shell

The protocol implementation is dependency-free (server.py) because the
official SDK needs Python 3.10 and the project runs on 3.9; the surface is
the standard one - initialize, tools/list, tools/call, resources - so any
MCP client can drive it.
"""
