# Deployment

The board is served from the machine that runs the stack, reached over a
Cloudflare Tunnel, behind Cloudflare Access. Nothing is hosted on
Cloudflare: the solver is a process pool over a real PostgreSQL database
and stays where the containers are. The tunnel is a door to it, not a
copy of it.

This is the only deployment the project has, and it changes one thing
about the threat model in [security.md](security.md): the board is
reachable from the internet. Read that document's *the perimeter*
section alongside this one.

## The shape

```
browser -> Cloudflare edge -> Access (email allowlist)
                           -> tunnel -> cloudflared on the host
                                     -> http://localhost:8017 (the ui container)
```

`cloudflared` runs on the host, not in a container: it dials out to the
edge, so no port is opened inbound and the machine needs no public
address. It reaches the board on the loopback publish the compose stack
already makes.

## What is exposed, and what is not

A tunnel carries the hostnames its ingress names and nothing else. The
config lives at `~/.cloudflared/config.yml` on the host:

| rule | service |
| --- | --- |
| `countrix.app` | `http://localhost:8017` |
| `www.countrix.app` | `http://localhost:8017` |
| anything else | `http_status:404` |

So the board, and only the board. PostgreSQL (5433), the inference
service (8019) and the MCP server (8020) are absent from the ingress and
still bind to 127.0.0.1, which is what keeps them unreachable. The MCP
server is the one that matters: it carries the tools that write, refresh
and rebuild, and its bearer token is optional and unset by default. It
is built for a Claude Code session on the same machine. Do not add it to
the ingress.

## The door

Cloudflare Access sits in front of both hostnames. An unauthenticated
request never reaches the tunnel: the edge answers `302` to the Access
login and the board's HTML is never sent. The policy is an allowlist of
email addresses, verified by a one-time PIN, so there is no identity
provider to configure and no password anywhere. A session lasts a day.

The board itself has no authentication and is not expected to grow any -
Access is the perimeter. That is the whole reason the ingress names one
port.

The board also runs read-only in this deployment:
`COUNTER_MATRIX_READ_ONLY` defaults to `1`, so `POST /api/weight`
answers 403 and a weight set on a slider is that session's own. See
[ui.md](ui.md). Turning it off would put a write endpoint on the public
internet behind nothing but Access; if you ever do, turn `sentry` back
on with it.

## The containers it runs

Five of the six, because the board needs five:

| service | why |
| --- | --- |
| `db` | the board queries PostgreSQL directly on every request |
| `ui` | the board itself, and the only service the tunnel names |
| `inference` | the solver; the board delegates to it over `INFERENCE_URL` |
| `data` | builds the database and applies migrations on boot, then idles |
| `refresher` | the daily 05:00 re-scrape, so the data does not go stale |

`sentry` is left out: it quarantines strategy files and audits, and
nothing that serves a request depends on it. With the board read-only no
strategy file changes from the web, so there is nothing for it to catch.
Bring it back if the board is ever made writable.

`data` is worth understanding: it is needed once, to build or migrate
the database, and then serves MCP that the read-only board never calls.
It cannot be dropped from the compose run - `ui` and `inference` wait on
its health - but it is not reachable from outside.

## Running it

The tunnel is a user LaunchAgent, `com.countrix.cloudflared`, which
starts at login and restarts on failure. Its log is
`~/Library/Logs/cloudflared-countrix.log`.

```bash
launchctl list | grep countrix                  # is it loaded
cloudflared tunnel info countrix                # the edge connections
launchctl unload ~/Library/LaunchAgents/com.countrix.cloudflared.plist
launchctl load -w ~/Library/LaunchAgents/com.countrix.cloudflared.plist
```

A LaunchAgent starts at login, not at boot; `sudo cloudflared service
install` makes it a system daemon instead. The stack behind it is
ordinary compose (`restart: unless-stopped`), so Docker must be set to
start with the machine or the tunnel will come up pointing at nothing -
which is a `502`, not an exposure.

The site is up while that machine is awake. There is no failover.

## Changing it

- **the hostnames**: edit the ingress in `~/.cloudflared/config.yml`,
  `cloudflared tunnel route dns countrix <host>` for the DNS, and add
  the host to the Access application, in that order - the Access policy
  before the DNS record, so there is no window where the board answers
  without a door.
- **the allowlist**: the Access application's policy, in the Zero Trust
  dashboard or over the API. Nothing in this repository holds it.
- **tearing it down**: `cloudflared tunnel delete countrix` revokes the
  credentials and the DNS records stop resolving to anything.

Credentials - the origin certificate and the tunnel's own secret - live
in `~/.cloudflared` on the host and are not in this repository. They are
the tunnel: anyone holding them can serve traffic for those hostnames.
