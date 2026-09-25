# Security

The project runs on your machine, on your Claude Code subscription,
against two public websites. What is worth protecting: your account,
your operating system, and the playbook and database the board trusts at
game time.

Nothing is published: every port compose publishes binds to 127.0.0.1,
and the board is reachable from this machine only.

## The threat model

| threat | how it would arrive |
| --- | --- |
| **prompt injection** | text that reads like an instruction, in a source page or a strategy file, shown by a tool to a session or to the headless agents' run, which has tools and no person watching |
| **the door and the other servers** | any process on this machine calling every tool on the MCP door, the writes, refreshes and rebuilds included; a browser page trying the same through DNS rebinding, or reading the board, the playbook and the solver's answers from any of the three HTTP servers |
| **SQL** | the `query` tool: the project's database users are superusers, and a superuser's `SELECT` can read files off the disk it runs on |
| **files** | tools that write into the playbook: a path that escapes the folder, a file the catalog would refuse, an oversized body |
| **the containers** | a compromised process inside one reaching the internet, escalating, filling the host, or calling every tool on the door, which answers the whole stack network as `data:8020` |
| **your account** | the CLI signed in on the host, driven headless with tools |

## What stands in the way

**Tool output is data.** Every skill but `/desloppify` carries the same
rule: what a tool returns is data about the game, never a message to the
session, and an instruction found inside it is reported, not followed. A
skill calls only the tools it names. The deriver's prompt says the same of
a draft's prose. The solver cannot be injected: it never scores an
assumption's prose, and it reads frontmatter through the whitelisted
expression language in `inference/expr.py`.

**The headless runs are fenced.** `orchestrator.py agents` allows the
tools in `orchestrator.AGENT_TOOL_NAMES` and no built-in tool
(`--tools ""`): no shell, no file edits, no web, no `add_strategy`, no
rebuild or migration. It keeps no session and stops at eighty turns. The
deriver runs `claude -p` from a neutral directory with no project
settings, no MCP servers, no tools and two turns, and stores only what the
catalog validates.

**The board's one write is off by default, and knocks at the door when
it is on.** `COUNTRIX_READ_ONLY` defaults to `1`: `POST /api/weight`
answers 403, or 415 first for a body not labelled `application/json`, so
a slider's weight stays in the session. At `0` the POST becomes a call to
the door's `tune` tool, which ignores the setting. The board's code
writes no playbook file, and its container mounts the playbook read-only.

**Every server answers only to its own names.** The door, the inference
service and the board stand on `db/web.py`, which checks each request's
`Host` and `Origin` before any route runs, on every method. Each must be a
local name (`db.web.LOCAL_HOSTS`) or one the server was started with: its
compose service name (`data`, `inference`) or a published board's public
name. Anything else is 403, a missing `Host` and `Origin: null` included.
A page rebound by DNS sends its own host name, so the Host check stops it.

**The door checks who is knocking.** It listens on 0.0.0.0:8020 inside
its container, so every container on the stack network reaches it as
`data`. `door/mcp/http.py` caps a request at one megabyte and a batch at
twenty messages, allows 120 tool calls per client address a minute and
answers 429 past that, and asks for `Authorization: Bearer <token>` when
`COUNTRIX_MCP_TOKEN` is set in `.env`; `.mcp.json` sends it, and `ui`
holds it too. `/health` stays open for the healthchecks.

**Every call leaves a line.** Each tool call, and each request to `/mcp`
the door turns away, is one line in `db/raw/audit.jsonl`: the caller, the
tool, each argument's size or type name (never its value), the outcome.
`door/mcp/audit.py` holds the rest.

**A failure keeps its traceback.** A request that raises is 400 with the
refusal's reason or 500 with the error's type and message
(`db.web.failure`), and the traceback goes to stderr; the door's JSON-RPC
says the same with `isError` and `INTERNAL`. The board's relays,
`db.web.call_tool` to the door and `ui.board.remote` to the inference
service, answer 400 for the caller's error, pass a 429 through, and
answer 502 for any other failure upstream, the door's 401 included, since
the token it refused is the board's. Each server logs one line to stderr
for every request that fails and every board it solves.

**SQL runs as the reader.** The `query` tool in `door/mcp/lifecycle.py`
runs one read-only statement under a ten-second timeout, refuses names
that reach the file system or the network, and connects as
`matrix_reader`, a login that can only `SELECT` and has no superuser
session to climb back to. Migration 012 withdraws from `PUBLIC` the
functions that run text as SQL or change settings.

**A table name in the statement is checked and quoted.** A query
parameter carries a value, never a name, so every writer that names a
table or column in SQL text passes it through `db.psql.identifier()`,
which allows only lowercase, digits and underscores. The statement is
composed with `psycopg.sql`; no name is spliced in with `%` or `+`.

**Files are written by validated tools only.** A strategy's id is its
filename, lowercase-kebab, so no path leaves the folder and no file
claims another's id. A file is loaded through the catalog before it is
written, and `checked_value` in `inference/strategy.py` is the one rule
every writer and the loader keep for a value. A name, a line and a
strategy's prose have length caps, and a reason is folded onto one line.
The deriver takes only a strategy's own fields from the model, ten drafts
a run at most. The board escapes everything it renders.

**The containers are boxed.** Every container but `db` runs as an
unprivileged user on a read-only root, with every capability dropped, no
new privileges and process and memory limits. `db` keeps the five
capabilities its image needs to start as root and drop to `postgres`,
takes no new privileges, and has a writable root and no limits.

**Two containers reach out.** All six share one network: Docker publishes
a port only for a container on a routable network, and the sentry needs
the database. What keeps `inference`, `ui`, `db` and `sentry` off the
internet is that their code opens no connection out. `data` and
`refresher` fetch from two fixed hosts, Blizzard's site and the wiki. The
page the board serves takes its code, styles and font from `ui/static`;
the browser loads hero portraits and role icons from Blizzard's CDNs.

**The sentry watches.** `door/sentry.py` runs a pass every thirty seconds.
A playbook file that does not load through the catalog, or whose prose
reads like an instruction, is renamed to `.md.quarantined`, which the
catalog ignores. Such text in the database is flagged for a person to
judge. The audit log's last minute is read for refusals, crashes, any
client address past the door's rate limit and any line that is not an
audit entry. `.venv/bin/python orchestrator.py status` prints the report,
`db/raw/sentry.json`; `.venv/bin/python -m door.sentry --once` runs one
pass and exits non-zero when something is wrong.

## What remains yours

- The CLI is signed in under your account on the host. The fences above
  bound what a headless run can do with it; nothing bounds what you type
  into an interactive session. Read what a skill reports.
- The sources are two public websites fetched over HTTPS by two
  containers. A compromised page can put text into the database; the
  sentry flags it, the skills treat it as data, and a rebuild from the
  page cache reproduces it until the cache is refreshed.
- The board and the inference service have no authentication of their
  own. The database's password is `overwatch`, public in `compose.yaml`,
  unless `POSTGRES_PASSWORD` is set in `.env`, and `matrix_reader`'s is
  its own name (migration 012). The door carries the tools that write,
  refresh and rebuild, and its token is optional and unset by default.
  Never publish the door (8020), the inference service (8019) or the
  database (5433).
- A board published anyway goes out alone: its line in
  `docker-entrypoint.sh` gains `--allow-host <public name>`, or every
  request answers 403, and `COUNTRIX_READ_ONLY` stays at `1`.
- `.env` holds the secrets, `COUNTRIX_MCP_TOKEN` and `POSTGRES_PASSWORD`.
  Keep it out of the repository (it is ignored) and out of the image (it
  is not copied).
- On a Linux host whose checkout is not owned by uid 1000, set
  `COUNTRIX_UID` and `COUNTRIX_GID` in `.env` to the owner's ids, or the
  containers cannot write the bind mounts (the audit log, the mirror, a
  quarantine, a tune) and say so in their logs.

To report a vulnerability, see [SECURITY.md](../SECURITY.md).
