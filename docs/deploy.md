# Deployment

**There is no deployment.** Every port binds to 127.0.0.1 and the board
is reachable from the machine running the stack and nowhere else. The
threat model in [security.md](security.md) assumes exactly that, and
nothing on this page changes it.

A Cloudflare Tunnel in front of this machine was set up and taken down
again on 2026-09-20; the reasoning and the commands are in the git
history, not here, because a document describing infrastructure that
does not exist is worse than no document. The next deployment will be a
VPS running the same compose stack, and this page gets written when it
is.

## What a deployment would need

The app cannot run on a serverless platform. The solver is a pool of six
to twelve OS processes over a real PostgreSQL database, with two daemon
loops beside it; that rules out Workers, Pages and anything Pyodide, and
makes a container host or a plain server the only honest options. See
[architecture.md](architecture.md) for why.

Five of the six services are needed to answer a request:

| service | why |
| --- | --- |
| `db` | the board queries PostgreSQL directly on every request |
| `ui` | the board itself, and the only port a deployment should expose |
| `inference` | the solver; the board delegates to it over `COUNTRIX_INFERENCE_URL` |
| `data` | builds the database and applies migrations on boot, then idles |
| `refresher` | the daily re-scrape, so the data does not go stale |

`sentry` quarantines strategy files and audits; nothing that serves a
request depends on it, so a read-only deployment can leave it out. Bring
it back with any board that writes.

`data` is the one worth understanding: it is needed once, to build or
migrate the database, and then serves an MCP endpoint the read-only
board never calls. It cannot be dropped from the compose run - `ui` and
`inference` wait on its health - but it need not be reachable.

## Three things to settle before anything is published

1. **The MCP server on 8020 carries the tools that write, refresh and
   rebuild, and its bearer token is optional and unset by default.** It
   is built for a Claude Code session on the same machine. Publishing it
   is the mistake to avoid; publish `ui` alone.
2. **The board has no authentication of its own** and is not expected to
   grow any, so whatever sits in front of it is the entire perimeter.
3. **The board must stay read-only.** `COUNTRIX_READ_ONLY` defaults to
   `1`, which makes `POST /api/weight` answer 403 and keeps a slider's
   weight inside the session ([ui.md](ui.md)). Turning it off puts a
   write endpoint on the internet.
