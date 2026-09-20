# Counter Utility Matrix

[![ci](https://github.com/mmikol/counter-utility-matrix/actions/workflows/ci.yml/badge.svg)](https://github.com/mmikol/counter-utility-matrix/actions/workflows/ci.yml)

Optimal Overwatch 2 team compositions: a database pulled from the
sources, a board that turns every pick into facts, and a deterministic
solver over a markdown playbook of constraints, heuristics and
assumptions. No accounts, no keys, no API billing.

## Install

- [Docker Desktop](https://www.docker.com/products/docker-desktop/), or any docker with compose v2
- Python 3.12 - the version the image runs - for the orchestrator, the tests and a Docker-less run (no PostgreSQL install: `pgserver` embeds one on macOS and Linux x86_64)
- [Claude Code](https://claude.com/claude-code) for the skills and the agents' run, signed in once with `claude login`

```bash
git clone git@github.com:mmikol/counter-utility-matrix.git && cd counter-utility-matrix
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Start

```bash
.venv/bin/python orchestrator.py
```

The stack comes up, one container per layer; the agents run headless on
the `/refresh` skill; the app is left running. The first start pulls
every source and builds the database, which takes minutes at a polite
pace.

| | |
| --- | --- |
| the board | **http://localhost:8017** |
| the inference service | http://localhost:8019 |
| the MCP server | http://localhost:8020/mcp |
| PostgreSQL | localhost:5433 (`./docker-db <command>` points a host command at it) |

Every port binds to 127.0.0.1 - a published board reaches the internet
through a tunnel to one of them, never a binding of its own; see
[docs/deploy.md](docs/deploy.md). Without the `claude` CLI signed in, the
run still brings the stack up and says what it skipped. The other verbs:

```bash
.venv/bin/python orchestrator.py up        # the stack only
.venv/bin/python orchestrator.py agents    # the agents' run only
.venv/bin/python orchestrator.py status    # what is running, how fresh the data is
.venv/bin/python orchestrator.py refresh   # refetch every source now
.venv/bin/python orchestrator.py test      # the test suite inside the image
.venv/bin/python orchestrator.py down      # stop everything; the database volume stays
```

Without Docker:

```bash
.venv/bin/python -m db.mcp call db_rebuild   # build the database (the embedded cluster)
.venv/bin/python -m ui.board                 # the board, http://localhost:8017
.venv/bin/ruff check db ui inference tests orchestrator.py   # the linter
.venv/bin/python -m pytest -q --cov   # the tests, under the 75% coverage bar
```

Open the repo in a Claude Code session and the skills are there: `/up`,
`/comp`, `/tune`, `/strategy`, `/patches`, `/heroes`, `/maps`,
`/refresh`, `/maintain`.

## License

Copyright (c) 2026 Miliano Mikol. Licensed under the
[PolyForm Strict License 1.0.0](LICENSE): noncommercial use only - no
redistribution, no changes or new works, no commercial use of any kind.
Anything else needs a separate written license from the author. The data
the app pulls - Blizzard's hero pages and the wiki - and the hero
portraits remain their owners'.

## Documentation

- [docs/architecture.md](docs/architecture.md) - the three layers, the folders, the root files, the diagrams, the scope
- [docs/db.md](docs/db.md) - the DATA LAYER: the sources, the tools, the schema, the refresh, the mirror
- [docs/ui.md](docs/ui.md) - the UI LAYER: the board, its endpoints, the facts behind it
- [docs/inference.md](docs/inference.md) - the INFERENCE LAYER: the strategy files, the solver, the tuning loop, the deriver, the catalog
- [docs/skills.md](docs/skills.md) - the skills a Claude Code session runs here
- [docs/mcp.md](docs/mcp.md) - the two MCP servers and every tool they expose
- [docs/security.md](docs/security.md) - the threat model and what stands in the way
- [docs/deploy.md](docs/deploy.md) - the DEPLOYMENT: the tunnel, the door, the containers it runs
