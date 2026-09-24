"""orchestrator.py with docker, the network and the claude CLI stubbed out: the
verdict, the dispatch, the agents' fences, the draft hand-off, each verb's calls."""

import json
import os
import re

import pytest

import orchestrator

REFRESH_SKILL = os.path.join(orchestrator.ROOT, ".claude", "skills", "refresh", "SKILL.md")


def test_verdict_reads_the_three_health_replies():
    ok, lines = orchestrator.verdict({
        "data": {"status": "ok", "state": "current", "table_count": 42, "heroes": 53,
                 "pending_migrations": [], "newest_capture": "2026-09-13"},
        "inference": {"status": "ok", "strategies": 38, "heroes": 53},
        "ui": {"heroes": [{}] * 53, "maps": [{}] * 30},
        "board": {"seconds": 1.0, "picks": []}})
    assert ok and lines == ["data layer: 42 tables, 53 heroes, rates captured 2026-09-13",
                            "inference: 38 strategies, 53 heroes, a board in 1.0s",
                            "board: 53 heroes on the roster, 30 maps"]
    ok, lines = orchestrator.verdict({
        "data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54,
                 "announced": 1, "pending_migrations": [], "newest_capture": "2026-09-14"},
        "inference": {"status": "ok", "strategies": 38, "heroes": 54},
        "ui": {"heroes": [{}] * 54, "maps": [{}] * 30},
        "board": {"seconds": 1.0, "picks": []}})
    assert ok and any("54 heroes (1 announced, not yet playable)" in line for line in lines)
    ok, lines = orchestrator.verdict({"data": {"status": "ok", "state": "stale",
                                               "table_count": 42, "heroes": 53,
                                               "pending_migrations": ["099_future.sql"]},
                                      "inference": {"status": "ok", "strategies": 0},
                                      "ui": None, "board": None})
    assert not ok
    assert [line.split(" (")[0] for line in lines] == [
        "data layer: schema behind the migrations", "data layer: 42 tables, 53 heroes,"
        " rates captured never", "inference: no strategies visible", "board: not answering"]
    assert "(099_future.sql)" in lines[0] and "stale bind mount" in lines[2]


def test_the_verdict_waits_on_the_data_layers_state():
    """Ready is the state the data layer reports, db.psql.schema.state; an
    image older than the checkout reports none, and is not ready either."""
    served = {
        "inference": {"status": "ok", "strategies": 38, "heroes": 54},
        "ui": {"heroes": [{}] * 54, "maps": [{}] * 30},
        "board": {"seconds": 1.0, "picks": []}}
    for state, said in (("empty", "no heroes yet"), ("unfilled", "no heroes yet"),
                        (None, "predates this checkout")):
        data = {"status": "ok", "table_count": 36, "heroes": 0, "pending_migrations": []}
        if state:
            data["state"] = state
        ok, lines = orchestrator.verdict(dict(served, data=data))
        assert not ok and any(said in line for line in lines), state


def test_health_urls_cover_every_served_layer():
    assert set(orchestrator.URLS) == {"data", "inference", "ui"}


def test_the_agents_run_is_headless_claude_on_the_refresh_skill(monkeypatch):
    command = orchestrator.agents_command(claude="/x/claude")
    assert command[:3] == ["/x/claude", "-p", "/refresh"]
    assert "--allowedTools" in command and orchestrator.AGENT_TOOLS in command
    assert "--no-session-persistence" in command and "--output-format" in command
    assert command[command.index("--tools") + 1] == "" and "--max-turns" in command
    allowed = set(orchestrator.AGENT_TOOLS.split(","))
    assert "mcp__countrix-docker__sync_all" in allowed
    assert "mcp__countrix__infer_strategy" in allowed
    assert "mcp__countrix-docker__query" in allowed      # read-only, its own login
    for never in ("add_strategy", "db_rebuild", "db_init", "db_migrate"):
        assert not any(t.endswith("__" + never) for t in allowed), never
    from inference import derive
    monkeypatch.setattr(derive, "cli", lambda: None)
    with pytest.raises(derive.CliUnavailableError, match="set COUNTRIX_CLAUDE"):
        orchestrator.agents_command()


@pytest.mark.skipif(not os.path.exists(REFRESH_SKILL), reason="the skills are not in the image")
def test_the_allowlist_is_exactly_the_tools_the_refresh_skill_names():
    from db.mcp import tools
    with open(REFRESH_SKILL, encoding="utf-8") as handle:
        named = set(re.findall(r"`([a-z_]+)`", handle.read()))
    registered = {name for name, *_ in tools.REGISTRY}
    assert set(orchestrator.AGENT_TOOL_NAMES) == named & registered


def test_no_verb_means_the_whole_run_and_a_bad_verb_prints_the_usage(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(orchestrator, "run", lambda: seen.append("run") or 0)
    monkeypatch.setattr(orchestrator, "status", lambda: seen.append("status") or 0)
    assert orchestrator.main([]) == 0 and orchestrator.main(["status"]) == 0
    assert seen == ["run", "status"]
    assert orchestrator.main(["dance"]) == 2
    assert "python orchestrator.py status" in capsys.readouterr().err


def test_sh_gives_up_on_a_command_past_its_timeout(monkeypatch):
    import subprocess
    given = []

    def overrun(argv, timeout=None):
        given.append(timeout)
        raise subprocess.TimeoutExpired(argv, timeout)
    monkeypatch.setattr(subprocess, "run", overrun)
    with pytest.raises(SystemExit, match="compose build data did not finish within 30 minutes"):
        orchestrator.sh("docker", "compose", "build", "data", timeout=30 * orchestrator.MINUTE)
    assert given == [1800]


def test_drafts_are_derived_on_the_host_then_the_stack_remirrors(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrator, "sh", lambda *a, **k: calls.append(("sh", a[-1])))
    monkeypatch.setattr(orchestrator, "mcp",
                        lambda name, args=None, **k: calls.append(("mcp", name)))
    assert orchestrator.derive_pending({"inference": {"strategies": 38, "pending": 0}}) is False
    assert orchestrator.derive_pending({"inference": None}) is False
    assert calls == []
    assert orchestrator.derive_pending({"inference": {"strategies": 39, "pending": 1}}) is True
    assert calls == [("sh", "derive_strategies"), ("mcp", "load_authored")]

    def refused(name, args=None, **k):
        raise RuntimeError("a bearer token is required")
    monkeypatch.setattr(orchestrator, "mcp", refused)
    with pytest.raises(SystemExit, match="load_authored failed: a bearer token"):
        orchestrator.derive_pending({"inference": {"strategies": 39, "pending": 1}})


# --- the verbs, with docker and the network stubbed out --------------------------------

@pytest.fixture()
def stubbed(monkeypatch):
    """Every side effect of the orchestrator recorded instead of run."""
    calls = []
    healthy = {"data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54,
                        "announced": 1, "pending_migrations": [],
                        "newest_capture": "2026-09-14"},
               "inference": {"status": "ok", "strategies": 38, "heroes": 54, "pending": 0},
               "ui": {"heroes": [{}] * 54, "maps": [{}] * 30},
               "board": {"seconds": 1.0, "picks": []}}
    # every command is given a timeout: a call without one raises TypeError here
    monkeypatch.setattr(orchestrator, "sh", lambda *a, timeout: calls.append(("sh", *a)) or "")
    monkeypatch.setattr(orchestrator, "wait_for", lambda url, s, what: calls.append(("wait", what)))
    monkeypatch.setattr(orchestrator, "health", lambda: healthy)
    monkeypatch.setattr(orchestrator, "mcp",
                        lambda name, args=None, **k: calls.append(("mcp", name)) or "ok")
    monkeypatch.setattr(orchestrator, "sentry_line",
                        lambda: "sentry: ok at now - 0 tool call(s) in the last minute")
    return calls, healthy


def test_up_builds_starts_waits_and_reports(stubbed, capsys):
    calls, _ = stubbed
    assert orchestrator.up() == 0
    assert ("sh", "docker", "compose", "build", "data") in calls
    assert ("wait", "the board") in calls
    assert "READY" in capsys.readouterr().out


def test_up_recreates_the_containers_when_a_bind_mount_went_stale(stubbed, capsys):
    calls, healthy = stubbed
    healthy["inference"]["strategies"] = 0
    healthy["inference"]["status"] = "degraded"
    assert orchestrator.up() == 1
    assert ("sh", "docker", "compose", "up", "-d", "--force-recreate") in calls
    assert "NOT READY" in capsys.readouterr().out


def test_status_reports_pending_drafts_without_deriving(stubbed, capsys):
    calls, healthy = stubbed
    healthy["inference"]["pending"] = 2
    assert orchestrator.status() == 0
    assert not any(c[0] in ("sh", "mcp") for c in calls)
    out = capsys.readouterr().out
    assert "2 draft(s) awaiting /strategy" in out and "sentry: ok" in out


def test_up_reads_the_health_again_after_deriving_drafts(stubbed, monkeypatch):
    calls, healthy = stubbed
    healthy["inference"]["pending"] = 2
    read = []
    monkeypatch.setattr(orchestrator, "health", lambda: read.append(1) or healthy)
    assert orchestrator.up() == 0
    assert len(read) == 2
    assert any(c[0] == "sh" and "derive_strategies" in c for c in calls)
    assert ("mcp", "load_authored") in calls


def test_refresh_test_down_and_main_dispatch(stubbed, monkeypatch, capsys):
    calls, _ = stubbed
    assert orchestrator.refresh() == 0 and ("mcp", "sync_all") in calls
    with monkeypatch.context() as patch:
        def refused(name, args=None, **k):
            raise RuntimeError("refused")
        patch.setattr(orchestrator, "mcp", refused)
        capsys.readouterr()
        assert orchestrator.refresh() == 1          # a refused sync_all is not done
        out = capsys.readouterr().out
        assert "NOT READY" in out and "sync_all failed - refused" in out
    assert orchestrator.test() == 0
    suite = next(c for c in calls if "pytest" in c)     # in the image, on the shipped playbook
    assert "COVERAGE_FILE=/tmp/.coverage" in suite and "COUNTRIX_STRATEGIES=" in suite
    assert orchestrator.down() == 0 and ("sh", "docker", "compose", "down") in calls
    assert orchestrator.main(["status"]) == 0
    capsys.readouterr()
    assert orchestrator.main(["up", "status"]) == 2
    assert "python orchestrator.py up" in capsys.readouterr().err


def test_agents_reports_a_missing_cli_and_a_signed_out_one(stubbed, monkeypatch, capsys):
    from inference import derive
    monkeypatch.setattr(derive, "cli", lambda: None)
    assert orchestrator.agents() == 1                     # no CLI: NOT READY, says so
    assert "no claude CLI" in capsys.readouterr().out
    monkeypatch.setattr(derive, "cli", lambda: "/usr/bin/false")
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 1, stdout="Not logged in", stderr=""))
    assert orchestrator.agents() == 0                     # signed out: skipped, the stack is up
    assert "not signed in" in capsys.readouterr().out
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout="refreshed", stderr=""))
    assert orchestrator.agents() == 0
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 3, stdout="boom", stderr=""))
    assert orchestrator.agents() == 1

    def overrun(*a, **k):
        raise subprocess.TimeoutExpired(a, k["timeout"])
    monkeypatch.setattr(subprocess, "run", overrun)
    capsys.readouterr()
    assert orchestrator.agents() == 1
    assert "did not finish within 4 hours" in capsys.readouterr().out


def test_run_brings_the_stack_up_and_skips_the_agents_without_a_cli(stubbed, monkeypatch, capsys):
    from inference import derive
    monkeypatch.setattr(derive, "available", lambda: False)
    assert orchestrator.run() == 0
    out = capsys.readouterr().out
    assert "agents: skipped" in out and "the app is up" in out


def test_dotenv_token_sentry_line_and_the_http_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "ROOT", str(tmp_path))
    assert orchestrator.dotenv() == {} and orchestrator.sentry_line() is None
    (tmp_path / ".env").write_text("# a comment\nCOUNTRIX_MCP_TOKEN='t0k'\nX=1\n")
    monkeypatch.delenv("COUNTRIX_MCP_TOKEN", raising=False)
    assert orchestrator.dotenv() == {"COUNTRIX_MCP_TOKEN": "t0k", "X": "1"}
    assert orchestrator.token() == "t0k"
    (tmp_path / ".env").unlink()
    (tmp_path / ".env").mkdir()                   # there, and unreadable: said, not skipped
    with pytest.raises(IsADirectoryError):
        orchestrator.dotenv()
    raw = tmp_path / "db" / "raw"
    raw.mkdir(parents=True)
    (raw / "sentry.json").write_text(json.dumps({
        "ok": False, "checked_at": "t", "quarantined": ["x.md"], "flags": ["f1"],
        "calls_last_minute": 4}))
    line = orchestrator.sentry_line()
    assert "FLAGS" in line and "quarantined x.md" in line and "1 flag(s): f1" in line
    # get_json swallows a dead endpoint; wait_for gives up loudly
    assert orchestrator.get_json("http://127.0.0.1:9/never", timeout=1) is None
    monkeypatch.setattr(orchestrator.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):
        orchestrator.wait_for("http://127.0.0.1:9/never", 0, "nothing")


def test_mcp_posts_a_tool_call_and_reads_the_text(monkeypatch):
    import io
    import urllib.request
    seen = {}

    class Reply(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(request, timeout=0):
        seen["url"], seen["body"] = request.full_url, json.loads(request.data.decode())
        seen["auth"] = request.get_header("Authorization")
        reply = {"result": {"content": [{"type": "text", "text": "hello"}]}}
        return Reply(json.dumps(reply).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("COUNTRIX_MCP_TOKEN", "t0k")
    assert orchestrator.mcp("db_status", {"a": 1}) == "hello"
    assert seen["body"]["params"] == {"name": "db_status", "arguments": {"a": 1}}
    assert seen["auth"] == "Bearer t0k"


def test_a_refused_or_unanswered_tool_call_raises_its_message(monkeypatch):
    """The tool's refusal, the door's 401 and no server at all each raise,
    so a caller never reads them as the tool's answer."""
    import io
    import urllib.error
    import urllib.request

    class Reply(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def refusing_tool(request, timeout=0):
        return Reply(json.dumps({"result": {"content": [{"type": "text", "text": "no source x"}],
                                            "isError": True}}).encode())

    def refusing_door(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(
            json.dumps({"error": "a bearer token is required"}).encode()))

    def nobody(request, timeout=0):
        raise urllib.error.URLError("connection refused")
    for urlopen, said in ((refusing_tool, "no source x"),
                          (refusing_door, "a bearer token is required"),
                          (nobody, "unreachable")):
        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        with pytest.raises(RuntimeError, match=said):
            orchestrator.mcp("sync_all")


def test_an_error_reply_reports_the_layers_own_message(monkeypatch):
    """A layer that answers with an error status is answering: get_json reads
    the body, and the verdict prints the layer's own words."""
    import io
    import urllib.error
    import urllib.request
    body = {}

    def failing(url, timeout=0):
        raise urllib.error.HTTPError(url, 500, "x", {}, io.BytesIO(body["raw"]))
    monkeypatch.setattr(urllib.request, "urlopen", failing)
    body["raw"] = json.dumps({"status": "degraded", "error": "no strategies in /x"}).encode()
    data = orchestrator.get_json("http://localhost:8020/health")
    assert data == {"status": "degraded", "error": "no strategies in /x"}
    body["raw"] = b"<html>a proxy's page</html>"
    assert orchestrator.get_json("http://localhost:8020/health") == {
        "status": "error", "error": "HTTP 500"}
    ok, lines = orchestrator.verdict({"data": data, "inference": None, "board": None,
                                      "ui": {"error": "TypeError: boom"}})
    assert not ok and "data layer: no strategies in /x" in lines
    assert "board: TypeError: boom" in lines


def test_readiness_solves_one_board_through_the_service(monkeypatch):
    """A six back from the probe means ready, anything else means not."""
    calls = []
    six = {"blue": {"blue": ["D.Va", "Winston", "Cassidy", "Genji", "Ana", "Brigitte"]}}
    monkeypatch.setattr(orchestrator, "get_json", lambda url, timeout=10: calls.append(url) or six)
    probe = orchestrator.probe()
    assert probe["picks"] == six["blue"]["blue"] and probe["seconds"] >= 0
    assert calls == [orchestrator.PROBE]
    monkeypatch.setattr(orchestrator, "get_json", lambda url, timeout=10: {"error": "died"})
    assert orchestrator.probe() is None
    inf = {"status": "ok", "strategies": 300, "heroes": 54}
    served = {"data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54},
              "inference": inf, "ui": {"heroes": [{}] * 54, "maps": [{}] * 30}}
    ok, lines = orchestrator.verdict(dict(served, board={"seconds": 2.4, "picks": six}))
    assert ok and any(line.endswith("a board in 2.4s") for line in lines)
    ok, lines = orchestrator.verdict(dict(served, board=None))
    assert not ok and any("a board did not solve" in line for line in lines)
