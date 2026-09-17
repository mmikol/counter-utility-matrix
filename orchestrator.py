"""The orchestrator: the end-to-end run, from a shell or a Claude Code session.

    python orchestrator.py            run: everything below, then leave the app up
    python orchestrator.py up         build the image, start the containers, wait -
                                      the data container pulls every source and
                                      ingests it when the database is empty or stale
    python orchestrator.py agents     Claude Code, headless, on the /refresh skill:
                                      refresh the data, complete the drafts,
                                      re-infer with restraint, regenerate the docs
    python orchestrator.py status     what is running, how fresh the data is, the URLs
    python orchestrator.py refresh    refetch every source now (no agents)
    python orchestrator.py test       the test suite inside the image, with the coverage bar
    python orchestrator.py down       stop everything (the database volume stays)

Everything the board uses at game time is deterministic - the database
and the strategy files. The agents run beforehand, on the host, on the
subscription (the claude CLI, signed in once), never at game time; when
the CLI is absent the run still brings the stack up and says what it
skipped. Nothing beyond the standard library and inference.derive. Exit code 0
means everything answered.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

URLS = {"data": "http://localhost:8020/health",
        "inference": "http://localhost:8019/health",
        "ui": "http://localhost:8017/api/roster"}
ROOT = os.path.dirname(os.path.abspath(__file__))
BOARD = "http://localhost:8017"


def sh(*args, check=True, capture=False, timeout=None):
    result = subprocess.run(list(args), text=True, timeout=timeout,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.STDOUT if capture else None)
    if check and result.returncode:
        raise SystemExit("error: %s exited %d%s" % (
            " ".join(args), result.returncode,
            "\n" + result.stdout[-2000:] if capture and result.stdout else ""))
    return result.stdout if capture else ""


def get_json(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_for(url, seconds, what):
    started = time.time()
    while time.time() - started < seconds:
        data = get_json(url)
        if data is not None:
            return data
        time.sleep(3)
    raise SystemExit("error: %s did not answer at %s within %ds" % (what, url, seconds))


def health():
    """{layer: json or None} for the three served layers."""
    return {layer: get_json(url) for layer, url in URLS.items()}


def verdict(h):
    """(ok, [lines]) from the health map - the checks that matter."""
    lines, ok = [], True
    data = h.get("data")
    if not data or data.get("status") != "ok":
        ok = False
        lines.append("data layer: not answering" if not data else
                     "data layer: %s" % data.get("error", data.get("status")))
    else:
        if data.get("pending_migrations"):
            ok = False
            lines.append("data layer: schema behind the migrations (%s)"
                         % ", ".join(data["pending_migrations"]))
        if not data.get("heroes"):
            ok = False
            lines.append("data layer: the database holds no heroes yet")
        lines.append("data layer: %d tables, %d heroes%s, rates captured %s"
                     % (data.get("tables", 0), data.get("heroes", 0),
                        " (%d announced, not yet playable)" % data["announced"]
                        if data.get("announced") else "",
                        data.get("newest_capture") or "never"))
    inf = h.get("inference")
    if not inf or inf.get("status") != "ok":
        ok = False
        lines.append("inference: not answering" if not inf else "inference: %s"
                     % inf.get("error", inf.get("status")))
    else:
        if not inf.get("strategies"):
            ok = False
            lines.append("inference: no strategies visible (a stale bind mount -"
                         " run `docker compose up -d --force-recreate`)")
        else:
            lines.append("inference: %d strategies, %d heroes%s"
                         % (inf["strategies"], inf.get("heroes", 0),
                            " - %d draft(s) awaiting /strategy" % inf["pending"]
                            if inf.get("pending") else ""))
    ui = h.get("ui")
    if not ui or "heroes" not in ui:
        ok = False
        lines.append("board: not answering")
    else:
        lines.append("board: %d heroes on the roster, %d maps"
                     % (len(ui["heroes"]), len(ui.get("maps", []))))
    return ok, lines


def dotenv():
    """KEY=VALUE lines of .env beside this file, if any: what compose reads."""
    out = {}
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


def token():
    return os.environ.get("COUNTER_MATRIX_MCP_TOKEN") or dotenv().get("COUNTER_MATRIX_MCP_TOKEN")


def mcp(name, arguments=None, timeout=600):
    """Call one tool on the stack's MCP endpoint -> its text."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments or {}}})
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token():
        headers["Authorization"] = "Bearer " + token()
    request = urllib.request.Request("http://localhost:8020/mcp", data=payload.encode(),
                                     headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode())
    if "error" in body:
        raise RuntimeError(body["error"].get("message", str(body["error"])))
    return body["result"]["content"][0]["text"]


def derive_pending(h):
    """Drafts in inference/strategies/ are completed on the host (the claude CLI
    lives here, not in the containers), then the stack's database re-mirrors."""
    pending = (h.get("inference") or {}).get("pending")
    if not pending:
        return
    print("%d draft strategy(ies) await frontmatter; deriving on the host..." % pending)
    sh(sys.executable, "-m", "db.mcp", "call", "derive_strategies")
    mcp("load_authored", {"only": ["strategies"]})


def up():
    print("building the image and starting the containers...")
    sh("docker", "compose", "build", "data")
    sh("docker", "compose", "up", "-d", "--remove-orphans")
    print("waiting for the layers (a first build scrapes the sources: minutes)...")
    wait_for(URLS["data"], 1800, "the data layer")
    wait_for(URLS["inference"], 600, "the inference engine")
    wait_for(URLS["ui"], 300, "the board")
    h = health()
    derive_pending(h)
    ok, lines = verdict(h)
    if not ok and h.get("inference") and not h["inference"].get("strategies"):
        print("stale bind mounts detected; recreating the containers...")
        sh("docker", "compose", "up", "-d", "--force-recreate")
        wait_for(URLS["inference"], 300, "the inference engine")
        wait_for(URLS["ui"], 120, "the board")
        ok, lines = verdict(health())
    return report(ok, lines)


def sentry_line():
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


def status():
    h = health()
    derive_pending(h)
    ok, lines = verdict(h if not (h.get("inference") or {}).get("pending") else health())
    seen = sentry_line()
    if seen:
        lines.append(seen)
    return report(ok, lines)


# The agents' run may call exactly these tools - the ones the /refresh skill
# names - on either server, and no built-in tool at all: no shell, no file
# edits, no web. Least privilege is what makes a headless run safe to schedule.
AGENT_TOOL_NAMES = ("db_status", "strategies", "tuning_log", "metrics", "facts", "infer",
                    "query", "sync_all", "pull_rates", "pull_counters", "load_authored",
                    "infer_strategy", "tune", "db_docs", "export_csv")
# A refresh pull fetches dozens of pages at a polite pace: minutes, not the
# seconds a tool call is given by default. The run's client waits this long.
AGENT_TOOL_TIMEOUT_MS = str(45 * 60 * 1000)
AGENT_TOOLS = ",".join("mcp__%s__%s" % (server, name)
                       for server in ("counter-utility-matrix-docker", "counter-utility-matrix")
                       for name in AGENT_TOOL_NAMES)


def agents_command(claude=None):
    """The headless run: Claude Code in print mode on the /refresh skill, with
    the stack's MCP tools allowed and nothing else."""
    from inference import derive
    binary = claude or derive.cli()
    if not binary:
        raise RuntimeError("no claude CLI on this machine (set %s)" % derive.CLI_ENV)
    return [binary, "-p", "/refresh", "--output-format", "text",
            "--mcp-config", os.path.join(ROOT, ".mcp.json"), "--strict-mcp-config",
            "--allowedTools", AGENT_TOOLS, "--tools", "", "--max-turns", "80",
            "--no-session-persistence"]


def agents():
    """The agents' run: refresh the database, complete the drafts, re-infer with
    restraint, regenerate the docs. Runs on the host, on the subscription;
    schedule it with cron or launchd."""
    print("agents: Claude Code, headless, on the /refresh skill (minutes)...")
    try:
        command = agents_command()
    except RuntimeError as error:
        return report(False, [str(error)])
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update({k: v for k, v in dotenv().items() if k not in env})   # the token, for .mcp.json
    env.setdefault("MCP_TOOL_TIMEOUT", AGENT_TOOL_TIMEOUT_MS)
    env.setdefault("MCP_TIMEOUT", AGENT_TOOL_TIMEOUT_MS)
    done = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True,
                          timeout=4 * 3600)
    said = (done.stdout.strip() + "\n" + done.stderr.strip()).strip()
    if done.returncode != 0 and ("Not logged in" in said or "/login" in said):
        print("agents: skipped - the claude CLI is not signed in; run `%s login` once on"
              " this machine (the stack is up; drafts stay pending, weights stay as they are)"
              % command[0])
        return 0
    print(said)
    if done.returncode != 0:
        return report(False, ["agents: claude -p exited %d" % done.returncode])
    return status()


def run():
    """Pull, ingest, infer, serve: the stack up, the agents' run when the CLI is
    here, and the app left running for the user."""
    code = up()
    if code:
        return code
    from inference import derive
    if derive.available():
        code = agents()
        if code:
            return code
    else:
        print("agents: skipped - no claude CLI signed in on this host (the stack is up;"
              " drafts stay pending, weights stay as they are)")
    print("\nthe app is up: %s" % BOARD)
    return 0


def report(ok, lines):
    for line in lines:
        print("  " + line)
    print("%s - board %s, inference :8019, MCP over HTTP :8020/mcp"
          % ("READY" if ok else "NOT READY", BOARD))
    return 0 if ok else 1


def refresh():
    print("refreshing every source through the data layer (minutes at a polite pace)...")
    print(mcp("sync_all", {"refresh": True}, timeout=3600))
    return status()


def test():
    """The suite inside the image: coverage writes to the tmpfs (the root is
    read-only), and the shipped playbook is used whatever experiment .env names."""
    sh("docker", "compose", "run", "--rm", "-e", "COVERAGE_FILE=/tmp/.coverage",
       "-e", "COUNTER_MATRIX_STRATEGIES=", "data",
       "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--cov")
    return 0


def down():
    sh("docker", "compose", "down")
    print("stopped; the database volume stays")
    return 0


def main(argv):
    verbs = {"run": run, "up": up, "agents": agents, "status": status,
             "refresh": refresh, "test": test, "down": down}
    if not argv:
        argv = ["run"]
    if len(argv) != 1 or argv[0] not in verbs:
        sys.exit(__doc__)
    return verbs[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
