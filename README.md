# Counter Utility Matrix

[![ci](https://github.com/mmikol/counter-utility-matrix/actions/workflows/ci.yml/badge.svg)](https://github.com/mmikol/counter-utility-matrix/actions/workflows/ci.yml)

Counter Utility Matrix: optimal Overwatch 2 team compositions from a database pulled from the sources,
a board that turns every pick into facts, and a deterministic solver over a
markdown playbook of constraints and heuristics. Free to run - no accounts,
no keys, no API billing.

## Install

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or any docker + compose v2)
- Python 3.12 for the orchestrator, the tests and a Docker-less run - the version the image runs (no PostgreSQL install needed: `pgserver` embeds one on macOS and Linux x86_64)
- [Claude Code](https://claude.com/claude-code), for the skills and the agents' run - signed in once with `claude login`

```bash
git clone git@github.com:mmikol/counter-utility-matrix.git && cd counter-utility-matrix
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Start

```bash
.venv/bin/python orchestrator.py
```

That is the whole run: the stack comes up (one container per layer; the
first time, the data container pulls every source and builds the database
- a few minutes, at a pace the sources can bear), the agents run headless
on the `/refresh` skill (refresh the data, derive draft strategies,
regenerate the docs), and the app is left running:

| | |
| --- | --- |
| the board | **http://localhost:8017** |
| the inference service | http://localhost:8019 |
| the MCP server | http://localhost:8020/mcp |
| PostgreSQL | localhost:5433 (`./docker-db <command>` points a host command at it) |

Every port binds to 127.0.0.1. Without the `claude` CLI signed in, the run
still brings the stack up and says what it skipped. The other verbs:

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
.venv/bin/python -m pytest -q --cov=db --cov=ui --cov=inference --cov=orchestrator   # the tests, under the 75% coverage bar
```

Open the repo in a Claude Code session and the skills are there: `/up`,
`/comp`, `/tune`, `/strategy`, `/patches`, `/heroes`, `/maps`, `/refresh`,
`/maintain`.

## License

Copyright (c) 2026 Miliano Mikol. Licensed under the
[PolyForm Strict License 1.0.0](LICENSE): you may use it for noncommercial
purposes, and that is all - no redistribution, no changes or new works
based on it, no commercial use of any kind. Any commercial use, and any
use outside those terms, needs a separate written license from the author.
The data the app pulls - Blizzard's hero pages, the wiki, the counterpick
lists - and the hero portraits remain their owners'.

## Documentation

- [docs/architecture.md](docs/architecture.md) - how the three layers fit: the folders, the root files, the diagrams, the skills, the scope
- [docs/db.md](docs/db.md) - the DATA LAYER: the sources, the MCP tools, the schema with its ER diagrams and data dictionary, the refresh, the mirror
- [docs/ui.md](docs/ui.md) - the UI LAYER: the board, its endpoints, the facts behind it
- [docs/inference.md](docs/inference.md) - the INFERENCE LAYER: the strategy files, the solver, the tuning loop, the deriver, the catalog
- [docs/skills.md](docs/skills.md) - the nine skills a Claude Code session runs here: what each takes, does, and refuses
- [docs/mcp.md](docs/mcp.md) - the two MCP servers and every tool they expose
- [docs/security.md](docs/security.md) - the threat model and what stands in the way: prompt injection, the door, SQL, files, the containers, the sentry
