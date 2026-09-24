"""The orchestrator: the end-to-end run, from a shell or a Claude Code session.

    python orchestrator.py            run: everything below, then leave the app up
    python orchestrator.py up         build the image, start the containers, wait -
                                      the data container builds the database when
                                      it is empty or stale; drafts pending in the
                                      playbook are completed on the host
    python orchestrator.py agents     Claude Code, headless, on the /refresh skill:
                                      refresh the data, complete the drafts,
                                      re-infer with restraint, regenerate the docs
    python orchestrator.py status     what is running, how fresh the data is, the URLs
    python orchestrator.py refresh    refetch every source now (no agents)
    python orchestrator.py test       the test suite inside the image, with the coverage bar
    python orchestrator.py down       stop everything (the database volume stays)

The agents run on the host, on the subscription (the claude CLI, signed in
once); without the CLI the run still brings the stack up and says so. It
imports the standard library, db's ROOT and inference.derive, the headless
claude recipe; run it with .venv/bin/python, since inference.derive loads
psycopg. Exit code 0 means everything answered.
"""

import json
import os
import subprocess  # nosec B404  # docker compose and the claude CLI, argv lists, never a shell
import sys
import time
import urllib.error
import urllib.request
from typing import Any, TypedDict

from db import ROOT
from inference import derive

URLS = {"data": "http://localhost:8020/health",
        "inference": "http://localhost:8019/health",
        "ui": "http://localhost:8017/api/roster"}
BOARD = "http://localhost:8017"
# one board solved through the service before the stack is called ready: only
# the container (1 GiB, a read-only root) shows whether this playbook fits its
# memory and time
PROBE = "http://localhost:8019/board?map=King%27s%20Row&red=Zarya&red=Pharah&side=attack"


def sh(*args: str) -> None:
    result = subprocess.run(list(args))
    if result.returncode:
        raise SystemExit("error: %s exited %d" % (" ".join(args), result.returncode))


def get_json(url: str | urllib.request.Request, timeout: float = 10) -> Any:
    """The JSON a URL or a request is answered with, an error status's body
    included, or None when nothing answers with JSON. An error status whose
    body is not JSON reads as {"status": "error", "error": "HTTP <code>"}."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # nosec B310  # http literals from the URL table
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:        # a URLError, so caught first
        try:
            return json.loads(error.read().decode("utf-8"))
        except ValueError:
            return {"status": "error", "error": "HTTP %d" % error.code}
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_for(url: str, seconds: int, what: str) -> Any:
    """The first JSON the URL answers, an error included, polled until
    `seconds` pass; then the run stops."""
    started = time.time()
    while time.time() - started < seconds:
        data = get_json(url)
        if data is not None:
            return data
        time.sleep(3)
    raise SystemExit("error: %s did not answer at %s within %ds" % (what, url, seconds))


class Probe(TypedDict):
    """One board solved through the inference service: how long it took, and
    blue's six."""
    seconds: float
    picks: list[str]


class Health(TypedDict):
    """What each served layer answered, None where nothing did, and the probe:
    None when the service could not solve a board or was never asked. The
    replies stay JSON off the wire; verdict reads them with .get."""
    data: dict[str, Any] | None
    inference: dict[str, Any] | None
    ui: dict[str, Any] | None
    board: Probe | None


def health() -> Health:
    """The three served layers' replies, and a board probed when the
    inference service answers."""
    replies = {layer: get_json(url) for layer, url in URLS.items()}
    return Health(data=replies["data"], inference=replies["inference"], ui=replies["ui"],
                  board=probe() if replies["inference"] else None)


def probe() -> Probe | None:
    """One board solved through the inference service -> {"seconds", "picks"},
    or None when the service did not answer with a six: unreachable, erroring,
    or a playbook whose limits seat no composition."""
    started = time.time()
    data = get_json(PROBE, timeout=120)
    picks = (data or {}).get("blue", {}).get("blue") or []
    if len(picks) != 6:                            # a six, or the service failed
        return None
    return Probe(seconds=round(time.time() - started, 1), picks=picks)


def _state_problem(data: dict[str, Any]) -> str | None:
    """Why the database is not ready, from the state the data layer's /health
    carries (db.psql.schema.state); None when it is current."""
    state = data.get("state")
    if state == "current":
        return None
    if state == "stale":
        return ("data layer: schema behind the migrations (%s)"
                % ", ".join(data.get("pending_migrations") or []))
    if state in ("empty", "unfilled"):
        return "data layer: the database holds no heroes yet"
    if state is None:
        return ("data layer: its /health carries no state - the image"
                " predates this checkout (`orchestrator.py up` rebuilds it)")
    return "data layer: the database is %s" % state


def data_verdict(data: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """The data layer answers, its database is current, and what it holds."""
    if not data:
        return False, ["data layer: not answering"]
    if data.get("status") != "ok":
        return False, ["data layer: %s" % data.get("error", data.get("status"))]
    announced = data.get("announced")
    summary = "data layer: %d tables, %d heroes%s, rates captured %s" % (
        data.get("table_count", 0), data.get("heroes", 0),
        " (%d announced, not yet playable)" % announced if announced else "",
        data.get("newest_capture") or "never")
    problem = _state_problem(data)
    return (False, [problem, summary]) if problem else (True, [summary])


def inference_verdict(inf: dict[str, Any] | None, board: Probe | None) -> tuple[bool, list[str]]:
    """The inference service answers, sees the playbook, and solves a board."""
    if not inf:
        return False, ["inference: not answering"]
    if inf.get("status") != "ok":
        return False, ["inference: %s" % inf.get("error", inf.get("status"))]
    if not inf.get("strategies"):
        return False, ["inference: no strategies visible (a stale bind mount -"
                       " run `docker compose up -d --force-recreate`)"]
    pending = inf.get("pending")
    summary = "inference: %d strategies, %d heroes%s" % (
        inf["strategies"], inf.get("heroes", 0),
        " - %d draft(s) awaiting /strategy" % pending if pending else "")
    if board is None:
        return False, [summary, "inference: a board did not solve - the service fails"
                                " under this playbook (`docker compose logs inference`)"]
    return True, [summary + ", a board in %.1fs" % board["seconds"]]


def ui_verdict(ui: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """The board answers with its roster."""
    if not ui:
        return False, ["board: not answering"]
    if "heroes" not in ui:
        return False, ["board: %s" % ui.get("error", "no roster in the reply")]
    return True, ["board: %d heroes on the roster, %d maps"
                  % (len(ui["heroes"]), len(ui.get("maps", [])))]


def verdict(h: Health) -> tuple[bool, list[str]]:
    """(ok, [lines]) from the health map: ok when every layer is, and the
    data layer's lines, then the inference service's, then the board's."""
    layers = (
        data_verdict(h["data"]),
        inference_verdict(h["inference"], h["board"]),
        ui_verdict(h["ui"]))
    return all(ok for ok, _ in layers), [line for _, lines in layers for line in lines]


def dotenv() -> dict[str, str]:
    """KEY=VALUE lines of .env beside this file, if any: what compose reads."""
    out: dict[str, str] = {}
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    out[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return out


def token() -> str | None:
    return os.environ.get("COUNTRIX_MCP_TOKEN") or dotenv().get("COUNTRIX_MCP_TOKEN")


def mcp(name: str, arguments: dict[str, Any] | None = None, timeout: float = 600) -> str:
    """Call one tool on the stack's MCP endpoint -> its text. A reply that is
    not the tool's answer raises RuntimeError with its message: the tool's
    refusal, the door turning the call away, or no server answering."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments or {}}})
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    bearer = token()
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    request = urllib.request.Request("http://localhost:8020/mcp", data=payload.encode(),
                                     headers=headers)
    body = get_json(request, timeout=timeout)
    if body is None:
        raise RuntimeError("the MCP server is unreachable at %s" % request.full_url)
    if "error" in body:                 # JSON-RPC's error object, or the door's string
        error = body["error"]
        raise RuntimeError(error.get("message", str(error)) if isinstance(error, dict)
                           else str(error))
    text = body["result"]["content"][0]["text"]
    if body["result"].get("isError"):
        raise RuntimeError(text)
    return text


def derive_pending(h: Health) -> bool:
    """Drafts in inference/strategies/ are completed on the host (the claude CLI
    lives here, not in the containers), then the stack's database re-mirrors.
    True when drafts were pending and the derive ran, so the health is stale."""
    pending = (h["inference"] or {}).get("pending")
    if not pending:
        return False
    print("%d draft strategy(ies) await frontmatter; deriving on the host..." % pending)
    sh(sys.executable, "-m", "db.mcp", "call", "derive_strategies")
    try:
        mcp("load_authored")
    except RuntimeError as error:
        raise SystemExit("error: load_authored failed: %s" % error) from error
    return True


def up() -> int:
    print("building the image and starting the containers...")
    sh("docker", "compose", "build", "data")
    sh("docker", "compose", "up", "-d", "--remove-orphans")
    print("waiting for the layers (a first build scrapes the sources: minutes)...")
    wait_for(URLS["data"], 1800, "the data layer")
    wait_for(URLS["inference"], 600, "the inference engine")
    wait_for(URLS["ui"], 300, "the board")
    h = health()
    if derive_pending(h):
        h = health()
    ok, lines = verdict(h)
    if not ok and h["inference"] and not h["inference"].get("strategies"):
        print("stale bind mounts detected; recreating the containers...")
        sh("docker", "compose", "up", "-d", "--force-recreate")
        wait_for(URLS["inference"], 300, "the inference engine")
        wait_for(URLS["ui"], 120, "the board")
        ok, lines = verdict(health())
    return report(ok, lines)


def sentry_line() -> str | None:
    """What the sentry last saw, from the report it leaves in db/raw."""
    path = os.path.join(ROOT, "db", "raw", "sentry.json")
    try:
        with open(path, encoding="utf-8") as handle:
            seen = json.load(handle)
    except (OSError, ValueError):
        return None
    parts = ["sentry: %s at %s" % ("ok" if seen.get("ok") else "FLAGS",
                                    seen.get("checked_at", "?"))]
    if seen.get("quarantined"):
        parts.append("quarantined %s" % ", ".join(seen["quarantined"]))
    if seen.get("flags"):
        parts.append("%d flag(s): %s" % (len(seen["flags"]), "; ".join(seen["flags"][:3])))
    parts.append("%d tool call(s) in the last minute" % seen.get("calls_last_minute", 0))
    return " - ".join(parts)


def status() -> int:
    ok, lines = verdict(health())
    seen = sentry_line()
    if seen:
        lines.append(seen)
    return report(ok, lines)


# The agents' run may call exactly these tools - the ones the /refresh skill
# names - on either server, and no built-in tool at all: no shell, no file
# edits, no web.
AGENT_TOOL_NAMES = ("db_status", "strategies", "tuning_log", "metrics", "facts", "infer",
                    "query", "sync_all", "pull_rates", "pull_counters", "pull_synergies",
                    "pull_seasons", "load_authored", "infer_strategy", "tune", "db_docs",
                    "export_csv", "reach")
# A refresh pull fetches dozens of pages at a polite pace: minutes, not the
# seconds a tool call is given by default.
AGENT_TOOL_TIMEOUT_MS = str(45 * 60 * 1000)
AGENT_TOOLS = ",".join("mcp__%s__%s" % (server, name)
                       for server in ("countrix-docker", "countrix")
                       for name in AGENT_TOOL_NAMES)


def agents_command(claude: str | None = None) -> list[str]:
    """The headless run: Claude Code in print mode on the /refresh skill, with
    the stack's MCP tools allowed and nothing else."""
    binary = claude or derive.require_cli()
    return [binary, "-p", "/refresh", "--output-format", "text",
            "--mcp-config", os.path.join(ROOT, ".mcp.json"), "--strict-mcp-config",
            "--allowedTools", AGENT_TOOLS, "--tools", "", "--max-turns", "80",
            "--no-session-persistence"]


def agents() -> int:
    """The agents' run, on the host, on the subscription; schedule it with cron
    or launchd."""
    print("agents: Claude Code, headless, on the /refresh skill (minutes)...")
    try:
        command = agents_command()
    except derive.CliUnavailableError as error:
        return report(False, [str(error)])
    env = derive.clean_env()
    env.update({k: v for k, v in dotenv().items() if k not in env})   # the token, for .mcp.json
    env.setdefault("MCP_TOOL_TIMEOUT", AGENT_TOOL_TIMEOUT_MS)
    env.setdefault("MCP_TIMEOUT", AGENT_TOOL_TIMEOUT_MS)
    done = subprocess.run(  # nosec B603  # argv from agents_command: the resolved claude binary and literal flags
        command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=4 * 3600)
    said = (done.stdout.strip() + "\n" + done.stderr.strip()).strip()
    if done.returncode != 0 and derive.not_signed_in(said):
        print("agents: skipped - the claude CLI is not signed in; run `%s login` once on"
              " this machine (the stack is up; drafts stay pending)" % command[0])
        return 0
    print(said)
    if done.returncode != 0:
        return report(False, ["agents: claude -p exited %d" % done.returncode])
    return status()


def run() -> int:
    """The stack up, the agents' run when the CLI is here, the app left running."""
    code = up()
    if code:
        return code
    if derive.available():
        code = agents()
        if code:
            return code
    else:
        print("agents: skipped - no claude CLI signed in on this host (the stack is up;"
              " drafts stay pending)")
    print("\nthe app is up: %s" % BOARD)
    return 0


def report(ok: bool, lines: list[str]) -> int:
    for line in lines:
        print("  " + line)
    print("%s - board %s, inference :8019, MCP over HTTP :8020/mcp"
          % ("READY" if ok else "NOT READY", BOARD))
    return 0 if ok else 1


def refresh() -> int:
    print("refreshing every source through the data layer (minutes at a polite pace)...")
    try:
        print(mcp("sync_all", {"refresh": True}, timeout=3600))
    except RuntimeError as error:
        return report(False, ["refresh: sync_all failed - %s" % error])
    return status()


def test() -> int:
    """The suite inside the image: coverage writes to the tmpfs (the root is
    read-only); the shipped playbook is used whatever .env names."""
    sh("docker", "compose", "run", "--rm", "-e", "COVERAGE_FILE=/tmp/.coverage",
       "-e", "COUNTRIX_STRATEGIES=", "data",
       "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--cov")
    return 0


def down() -> int:
    sh("docker", "compose", "down")
    print("stopped; the database volume stays")
    return 0


def main(argv: list[str]) -> int:
    verbs = {"run": run, "up": up, "agents": agents, "status": status,
             "refresh": refresh, "test": test, "down": down}
    if not argv:
        argv = ["run"]
    if len(argv) != 1 or argv[0] not in verbs:
        sys.exit(__doc__)
    return verbs[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
