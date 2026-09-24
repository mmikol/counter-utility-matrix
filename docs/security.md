# Security

The project runs on your machine, on your Claude Code subscription,
against two public websites. What is worth protecting: your account,
your operating system, and the playbook and database the board trusts at
game time.

Nothing is published: every port binds to 127.0.0.1 and the board is
reachable from this machine only ([deploy.md](deploy.md)).

## The threat model

| threat | how it would arrive |
| --- | --- |
| **prompt injection** | text from a source page (an ability description, a wiki note) or a strategy file that reads like an instruction, shown to a session by a tool - or to the headless agents' run, which has tools and no person watching |
| **the door** | the MCP server over HTTP: any process on this machine can call every tool, including the ones that write, refresh or rebuild; a browser page could try the same through DNS rebinding |
| **SQL** | the `query` tool: the project's database users are superusers, and a superuser's `SELECT` can read files off the disk it runs on |
| **files** | tools that write into the playbook: a path that escapes the folder, a file the catalog would refuse, an oversized body |
| **the containers** | a compromised process inside one reaching the internet, escalating, or filling the host |
| **your account** | the CLI signed in on the host, driven headless with tools |

## What stands in the way

**Tool output is data.** Every skill carries the same rule: what a tool
returns - facts, source text, notes, prose - is data about the game,
never a message to the session; an instruction found inside it is
reported, not followed, and a skill calls only the tools it names. The
deriver's prompt says the same of a draft's prose. The solver cannot be
injected: an assumption is prose it never scores, and it reads
frontmatter through a whitelisted expression language (no attribute
access, no dunder names, a fixed function set, `__builtins__` empty,
exponents bounded, no string arithmetic, nesting bounded).

**The headless runs are fenced.** `orchestrator.py agents` gives Claude
Code in print mode an explicit allowlist of tools on the two servers -
status, the catalog, the log, the vocabulary, facts, inference,
read-only `query`, the refresh and load tools, `infer_strategy`, `tune`,
`db_docs`, `export_csv` - and no built-in tool at all (`--tools ""`): no
shell, no file edits, no web, no `add_strategy`, no rebuild or migration,
no session kept afterwards, at most eighty turns, and a tool-call timeout
long enough for a polite scrape (`MCP_TOOL_TIMEOUT`). The deriver runs
`claude -p` from a neutral directory with no project settings, no MCP
servers, no tools and two turns, and stores only what the catalog
validates.

**The board's one write is off by default, and knocks at the door when
it is on.** `COUNTRIX_READ_ONLY` defaults to `1`: the board offers
no *store* button and answers `POST /api/weight` with 403, so a weight
set on a slider is the session's own and reaches no file. The data
layer's `tune` tool is deliberately unaffected - a Claude Code session
still writes weights through it. With `COUNTRIX_READ_ONLY=0` the
write comes back: `POST /api/weight` on the board (bound to 127.0.0.1
like everything else, and behind the data layer's two browser guards - a
non-local `Origin` is refused with 403, a body that does not claim
`application/json` with 415), which the board turns into a `tune` call - over HTTP to the MCP server with the bearer token in the
compose stack, in-process through the same tool registry on the local
cluster - so the change is validated against the catalog, logged with its
reason and mirrored like any other. The board never opens a playbook
file, and its container mounts the playbook read-only.

**The door checks who is knocking.** The HTTP server binds to 127.0.0.1,
refuses browser origins that are not local (DNS-rebinding guard), caps a
request at one megabyte and a batch at twenty messages, allows 120 tool
calls per client address per minute (the limit is per address, not per
claimed session id) and answers 429 past that, and - when
`COUNTRIX_MCP_TOKEN` is set in `.env` - requires
`Authorization: Bearer <token>` on every call (the session sends it from
`.mcp.json`; `/health` stays open for the healthchecks). Every tool call is
one line in the audit log `db/raw/audit.jsonl`: when, transport (`stdio`,
`http` or `in-process`, the last being the refresher's and the shell's
direct calls), client, tool, the names and sizes of its arguments (never
their values), outcome, duration.

**A failure says what failed, never where.** The board and the inference
service answer a request that raises through `db/web.py`: a refusal - an
unknown hero, a malformed weight - is 400 with its reason, and anything
else is 500 with the error's type and message, its traceback written to
stderr and never into the reply. The MCP door draws the same line in
JSON-RPC's words: a refusal is `isError`, anything else `INTERNAL`, the
traceback in its log.

**SQL reads tables, not disks.** The `query` tool accepts one statement
that starts `SELECT`, `WITH`, `EXPLAIN`, `SHOW`, `TABLE` or `VALUES`,
refuses names that reach the file system or the network before the
database sees them, and connects as `matrix_reader` - a login of its own
with `SELECT` on tables and nothing else (migrations 011 and 012), so a
superuser-only function fails even if a name slipped past the list, and
there is no superuser session to climb back to. The functions that run
text as SQL or change settings are withdrawn from `PUBLIC`. The statement
runs read-only under a ten-second timeout; the first 200 rows come back,
a result is capped at a megabyte, cells at two thousand characters.

**A table name in the statement is checked and quoted.** psycopg
parameterises values and never identifiers, so the writers that name a
table or column in the SQL text itself - the exports, the stat inserts,
the terrain store, the lookups, the sentry's scan, `db_status`'s counts -
pass the name through `psql.identifier()`, which refuses anything but
lowercase, digits and underscores and returns a `psycopg.sql.Identifier`.
The statement is composed with `psycopg.sql.SQL`, which quotes it; no name
is spliced into SQL text with `%` or `+`. Every such name comes from a
literal or from the catalog today; the check is what keeps a later caller
from changing that quietly.

**Files are written by validated tools only.** A strategy's id is its
filename, lowercase-kebab and nothing else, so no path leaves the folder
and no file can claim another's id; a file is loaded through the catalog
before it exists or changes; a frontmatter value is one line and a weight
is within 0..10; names, prose, questions, reasoning and notes have length
caps; the deriver accepts only a strategy's own fields from the model, at
most ten drafts a run, and passes a draft's prose over stdin; a search's
pool and its alternatives are clamped. The board escapes everything it
renders.

**The containers are boxed.** Every container runs as an unprivileged
user on a read-only root filesystem (only the bind mounts and `/tmp` are
writable), with every capability dropped, no new privileges, a process
limit and a memory limit, and restart if they fall over; the database
container keeps only the five capabilities its image needs to start. They
share one network: Docker publishes a port only for a container on a
routable network, and the sentry needs the database, so what keeps
`inference`, `ui`, `db` and `sentry` off the internet is that their code
opens no connection out - only the two pull-side containers fetch
anything, from two fixed hosts: Blizzard's site and the wiki. Every
published port binds to 127.0.0.1.

**The sentry watches.** The `sentry` container (`db/sentry.py`) checks, every
thirty seconds: that every file in `inference/strategies/` loads through
the catalog - one that does not is quarantined (renamed to
`.md.quarantined`, which the catalog ignores) and named in the report;
that no strategy's prose reads like an instruction ("ignore previous
instructions", a shell command, a credential, a script tag, a base64
blob) - one that does is quarantined the same way; that the free text in
the database (descriptions, the wiki's notes, strategy bodies) carries no
such text - those are flagged, not removed, a person decides; and what the
audit log says about the last minute - calls, refusals, crashes, any
client past the rate limit, and any line that is not an audit entry. The
scan folds Unicode to one shape and strips zero-width characters first,
so a word broken by an invisible character still reads as the word. Its
report is `db/raw/sentry.json`, and `python orchestrator.py status`
prints it. `python -m db.sentry --once` runs one pass from a shell and
exits non-zero when something is wrong.

## What remains yours

- The CLI is signed in under your account on the host. The fences above
  bound what a headless run can do with it; nothing bounds what you type
  into an interactive session. Read what a skill reports.
- The sources are two public websites fetched over HTTPS by two
  containers. A compromised page can put text into the database; the
  sentry flags it, the skills treat it as data, and a rebuild from the
  page cache reproduces it until the cache is refreshed.
- The board, the inference service and the database have no
  authentication of their own; they are reachable from this machine only.
  Do not publish those ports.
- Keep `.env` out of the repository (it is ignored) and out of the image
  (it is not copied). There are no other secrets.
- On a Linux host whose checkout is not owned by uid 1000, set
  `COUNTRIX_UID` and `COUNTRIX_GID` in `.env` to the owner's
  ids, or the containers cannot write the bind mounts (the audit log, the
  mirror, a quarantine, a tune) and say so in their logs.

Report a vulnerability privately to the repository owner rather than in a
public issue; see [SECURITY.md](../SECURITY.md). None of this is a
commitment: you run the software at your own risk, and the author
promises no response time and no fix. These measures describe what the
code does, not that it is enough for you.
