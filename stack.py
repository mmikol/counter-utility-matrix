"""The stack, from a shell or a Claude Code session: build it, start it, wait
until every layer is healthy and the data is current, and say so.

    python stack.py up        build the image, start the containers, wait, report
    python stack.py status    what is running, how fresh the data is, the URLs
    python stack.py refresh   refetch every source now (through the data layer)
    python stack.py test      the test suite inside the image
    python stack.py down      stop everything (the database volume stays)

Standard library only. Exit code 0 means everything answered.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

URLS = {"data": "http://localhost:8020/health",
        "inference": "http://localhost:8019/health",
        "ui": "http://localhost:8017/api/roster"}
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
        lines.append("data layer: %d tables, %d heroes, %d outcomes, rates captured %s"
                     % (data.get("tables", 0), data.get("heroes", 0),
                        data.get("outcomes", 0), data.get("newest_capture") or "never"))
    inf = h.get("inference")
    if not inf or inf.get("status") != "ok":
        ok = False
        lines.append("inference: not answering" if not inf else "inference: %s"
                     % inf.get("error", inf.get("status")))
    else:
        if not inf.get("heuristics"):
            ok = False
            lines.append("inference: no heuristics visible (a stale bind mount -"
                         " run `docker compose up -d --force-recreate`)")
        else:
            lines.append("inference: %d heuristics, %d heroes"
                         % (inf["heuristics"], inf.get("heroes", 0)))
    ui = h.get("ui")
    if not ui or "heroes" not in ui:
        ok = False
        lines.append("board: not answering")
    else:
        lines.append("board: %d heroes on the roster, %d maps"
                     % (len(ui["heroes"]), len(ui.get("maps", []))))
    return ok, lines


def up():
    print("building the image and starting the containers...")
    sh("docker", "compose", "build", "data")
    sh("docker", "compose", "up", "-d", "--remove-orphans")
    print("waiting for the layers (a first build scrapes the sources: minutes)...")
    wait_for(URLS["data"], 1800, "the data layer")
    wait_for(URLS["inference"], 300, "the inference engine")
    wait_for(URLS["ui"], 120, "the board")
    h = health()
    ok, lines = verdict(h)
    if not ok and h.get("inference") and not h["inference"].get("heuristics"):
        print("stale bind mounts detected; recreating the containers...")
        sh("docker", "compose", "up", "-d", "--force-recreate")
        wait_for(URLS["inference"], 300, "the inference engine")
        wait_for(URLS["ui"], 120, "the board")
        ok, lines = verdict(health())
    return report(ok, lines)


def status():
    ok, lines = verdict(health())
    return report(ok, lines)


def report(ok, lines):
    for line in lines:
        print("  " + line)
    print("%s - board %s, inference :8019, MCP over HTTP :8020/mcp"
          % ("READY" if ok else "NOT READY", BOARD))
    return 0 if ok else 1


def refresh():
    print("refreshing every source through the data layer (minutes at a polite pace)...")
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "sync_all", "arguments": {"refresh": True}}})
    request = urllib.request.Request("http://localhost:8020/mcp", data=payload.encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=3600) as response:
        reply = json.loads(response.read().decode("utf-8"))
    print(reply["result"]["content"][0]["text"])
    return status()


def test():
    sh("docker", "compose", "run", "--rm", "data", "python", "-m", "pytest", "-q")
    return 0


def down():
    sh("docker", "compose", "down")
    print("stopped; the database volume stays")
    return 0


def main(argv):
    verbs = {"up": up, "status": status, "refresh": refresh, "test": test, "down": down}
    if len(argv) != 1 or argv[0] not in verbs:
        sys.exit(__doc__)
    return verbs[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
