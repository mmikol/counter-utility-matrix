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
imports the standard library, db's ROOT, db.web's MCP client and
inference.derive, the headless claude recipe; run it with .venv/bin/python,
since inference.derive loads psycopg. Exit code 0 means everything answered.
"""

import json
import os
import subprocess  # nosec B404  # docker compose and the claude CLI, argv lists, never a shell
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import timedelta
from typing import Any, NamedTuple, TypedDict

from db import ROOT, web
from inference import derive

# the compose stack's ports on this host (compose.yaml)
DATA = "http://localhost:8020"
INFERENCE = "http://localhost:8019"
BOARD = "http://localhost:8017"
URLS = {"data": DATA + "/health", "inference": INFERENCE + "/health", "ui": BOARD + "/api/roster"}
MCP_URL = DATA + "/mcp"
# one board solved through the service before the stack is called ready: only
# the container (1 GiB, a read-only root) shows whether this playbook fits its
# memory and time
PROBE = INFERENCE + "/board?map=King%27s%20Row&red=Zarya&red=Pharah&side=attack"

MINUTE = 60                         # seconds
HOUR = 60 * MINUTE
# a derive on the host: every draft refused once, each attempt at the CLI's
# timeout, then the mirror
DERIVE_TIMEOUT = 2 * derive.MAX_PER_RUN * derive.TIMEOUT + 5 * MINUTE


def sh(*args: str, timeout: float) -> None:
    """Run one command; a failure or an overrun past `timeout` seconds stops
    the run."""
    try:
        result = subprocess.run(  # nosec B603  # argv lists built here from literals and this interpreter, never a shell
            list(args), timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise SystemExit("error: %s did not finish within %d minutes"
                         % (" ".join(args), timeout // MINUTE)) from error
    if result.returncode:
        raise SystemExit("error: %s exited %d" % (" ".join(args), result.returncode))


def _json_object(raw: bytes) -> dict[str, Any]:
    """The JSON object a body holds; ValueError for anything else."""
    reply = json.loads(raw.decode("utf-8"))
    if not isinstance(reply, dict):
        raise ValueError("not a JSON object")
    return reply


def get_json(url: str, timeout: float = 10) -> dict[str, Any] | None:
    """The JSON object a URL is answered with, an error status's
    body included, or None when nothing answers with one. An error status
    whose body is not a JSON object reads as {"status": "error", "error":
    "HTTP <code>"}."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # nosec B310  # http literals from the URL table
            return _json_object(response.read())
    except urllib.error.HTTPError as error:        # a URLError, so caught first
        try:
            return _json_object(error.read())
        except ValueError:
            return {"status": "error", "error": "HTTP %d" % error.code}
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_for(url: str, seconds: float, what: str) -> dict[str, Any]:
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


class Verdict(NamedTuple):
    """Whether a layer, or the whole stack, is ready, and the lines that say so."""
    ok: bool
    lines: list[str]


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
    data = get_json(PROBE, timeout=2 * MINUTE)
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


def data_verdict(data: dict[str, Any] | None) -> Verdict:
    """The data layer answers, its database is current, and what it holds."""
    if not data:
        return Verdict(False, ["data layer: not answering"])
    if data.get("status") != "ok":
        return Verdict(False, ["data layer: %s" % data.get("error", data.get("status"))])
    announced = data.get("announced")
    summary = "data layer: %d tables, %d heroes%s, rates captured %s" % (
        data.get("table_count", 0), data.get("heroes", 0),
        " (%d announced, not yet playable)" % announced if announced else "",
        data.get("newest_capture") or "never")
    problem = _state_problem(data)
    return Verdict(False, [problem, summary]) if problem else Verdict(True, [summary])


def inference_verdict(inf: dict[str, Any] | None, board: Probe | None) -> Verdict:
    """The inference service answers, sees the playbook, and solves a board."""
    if not inf:
        return Verdict(False, ["inference: not answering"])
    if inf.get("status") != "ok":
        return Verdict(False, ["inference: %s" % inf.get("error", inf.get("status"))])
    if not inf.get("strategies"):
        return Verdict(False, ["inference: no strategies visible (a stale bind mount -"
                               " run `docker compose up -d --force-recreate`)"])
    pending = inf.get("pending")
    summary = "inference: %d strategies, %d heroes%s" % (
        inf["strategies"], inf.get("heroes", 0),
        " - %d draft(s) awaiting /strategy" % pending if pending else "")
    if board is None:
        return Verdict(False, [summary, "inference: a board did not solve - the service"
                                        " fails under this playbook (`docker compose logs"
                                        " inference`)"])
    return Verdict(True, [summary + ", a board in %.1fs" % board["seconds"]])


def ui_verdict(ui: dict[str, Any] | None) -> Verdict:
    """The board answers with its roster."""
    if not ui:
        return Verdict(False, ["board: not answering"])
    if "heroes" not in ui:
        return Verdict(False, ["board: %s" % ui.get("error", "no roster in the reply")])
    return Verdict(True, ["board: %d heroes on the roster, %d maps"
                          % (len(ui["heroes"]), len(ui.get("maps", [])))])


def verdict(h: Health) -> Verdict:
    """The stack's verdict from the health map: ok when every layer is, and the
    data layer's lines, then the inference service's, then the board's."""
    layers = (
        data_verdict(h["data"]),
        inference_verdict(h["inference"], h["board"]),
        ui_verdict(h["ui"]))
    return Verdict(all(layer.ok for layer in layers),
                   [line for layer in layers for line in layer.lines])


def dotenv() -> dict[str, str]:
    """KEY=VALUE lines of .env beside this file: what compose reads. No .env
    reads as none; one that cannot be read raises."""
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return {}
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip("'\"")
    return out


def token() -> str | None:
    """The MCP door's bearer token: the environment's, else .env's."""
    return os.environ.get("COUNTRIX_MCP_TOKEN") or dotenv().get("COUNTRIX_MCP_TOKEN")


def mcp(name: str, arguments: dict[str, Any] | None = None, timeout: float = 10 * MINUTE) -> str:
    """Call one tool on the stack's MCP endpoint -> its text. A reply that is
    not the tool's answer raises RuntimeError with its message: the tool's
    refusal, the door turning the call away, or no server answering."""
    reply = web.call_tool(MCP_URL, name, arguments or {}, token=token(), timeout=timeout)
    if reply.is_error:
        raise RuntimeError(reply.text)
    return reply.text


def derive_pending(h: Health) -> bool:
    """Drafts in inference/strategies/ are completed on the host (the claude CLI
    lives here, not in the containers), then the stack's database re-mirrors.
    True when drafts were pending and the derive ran, so the health is stale."""
    pending = (h["inference"] or {}).get("pending")
    if not pending:
        return False
    print("%d draft strategy(ies) await frontmatter; deriving on the host..." % pending)
    sh(sys.executable, "-m", "db.mcp", "call", "derive_strategies", timeout=DERIVE_TIMEOUT)
    try:
        mcp("load_authored")
    except RuntimeError as error:
        raise SystemExit("error: load_authored failed: %s" % error) from error
    return True


def up() -> int:
    """Build the image, start the containers, wait for each layer, complete
    pending drafts on the host -> the verdict's exit code."""
    print("building the image and starting the containers...")
    sh("docker", "compose", "build", "data", timeout=30 * MINUTE)
    sh("docker", "compose", "up", "-d", "--remove-orphans", timeout=10 * MINUTE)
    print("waiting for the layers (a first build scrapes the sources: minutes)...")
    wait_for(URLS["data"], 30 * MINUTE, "the data layer")
    wait_for(URLS["inference"], 10 * MINUTE, "the inference engine")
    wait_for(URLS["ui"], 5 * MINUTE, "the board")
    h = health()
    if derive_pending(h):
        h = health()
    ok, lines = verdict(h)
    if not ok and h["inference"] and not h["inference"].get("strategies"):
        print("stale bind mounts detected; recreating the containers...")
        sh("docker", "compose", "up", "-d", "--force-recreate", timeout=10 * MINUTE)
        wait_for(URLS["inference"], 5 * MINUTE, "the inference engine")
        wait_for(URLS["ui"], 2 * MINUTE, "the board")
        ok, lines = verdict(health())
    return report(ok, lines)


def sentry_line() -> str | None:
    """What the sentry last saw, from the report it leaves in db/raw
    (db.sentry.Report); None without one, or when it is not a JSON object."""
    path = os.path.join(ROOT, "db", "raw", "sentry.json")
    try:
        with open(path, "rb") as handle:
            seen = _json_object(handle.read())
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
    """The verdict and the sentry's last pass, touching nothing."""
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
# seconds a tool call is given by default. MCP_TOOL_TIMEOUT is read in
# milliseconds.
AGENT_TOOL_TIMEOUT_MS = str(timedelta(minutes=45) // timedelta(milliseconds=1))
AGENT_RUN_TIMEOUT = 4 * HOUR
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
    try:
        done = subprocess.run(  # nosec B603  # argv from agents_command: the resolved claude binary and literal flags
            command, cwd=ROOT, env=env, text=True, capture_output=True,
            timeout=AGENT_RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return report(False, ["agents: claude -p did not finish within %d hours"
                              % (AGENT_RUN_TIMEOUT // HOUR)])
    said = (done.stdout.strip() + "\n" + done.stderr.strip()).strip()
    if done.returncode != 0 and derive.not_signed_in(said):
        print(
            "agents: skipped - the claude CLI is not signed in; run `%s login` once on"
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
        print(
            "agents: skipped - no claude CLI signed in on this host (the stack is up;"
            " drafts stay pending)")
    print("\nthe app is up: %s" % BOARD)
    return 0


def report(ok: bool, lines: list[str]) -> int:
    """Print the lines, then READY or NOT READY with the URLs -> the exit code."""
    for line in lines:
        print("  " + line)
    print(
        "%s - board %s, inference %s, MCP over HTTP %s"
        % ("READY" if ok else "NOT READY", BOARD, INFERENCE, MCP_URL))
    return 0 if ok else 1


def refresh() -> int:
    """Refetch every source through the data layer's sync_all, then the status."""
    print("refreshing every source through the data layer (minutes at a polite pace)...")
    try:
        print(mcp("sync_all", {"refresh": True}, timeout=HOUR))
    except RuntimeError as error:
        return report(False, ["refresh: sync_all failed - %s" % error])
    return status()


def test() -> int:
    """The suite inside the image: coverage writes to the tmpfs (the root is
    read-only); the shipped playbook is used whatever .env names."""
    sh(
        "docker", "compose", "run", "--rm", "-e", "COVERAGE_FILE=/tmp/.coverage",
        "-e", "COUNTRIX_STRATEGIES=", "data",
        "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--cov", timeout=HOUR)
    return 0


def down() -> int:
    """Stop the containers; the database volume stays."""
    sh("docker", "compose", "down", timeout=5 * MINUTE)
    print("stopped; the database volume stays")
    return 0


def main(argv: list[str]) -> int:
    """Run one verb, `run` when none is named -> its exit code; 2, with the
    usage on stderr, for anything else."""
    verbs: dict[str, Callable[[], int]] = {
        "run": run, "up": up, "agents": agents, "status": status, "refresh": refresh,
        "test": test, "down": down}
    verb = argv[0] if argv else "run"
    if len(argv) > 1 or verb not in verbs:
        print(__doc__, file=sys.stderr)
        return 2
    return verbs[verb]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
