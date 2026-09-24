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
        "ui": {"heroes": [{}] * 53, "maps": [{}] * 30}})
    assert ok and any("rates captured 2026-09-13" in line for line in lines)
    ok, lines = orchestrator.verdict({
        "data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54,
                 "announced": 1, "pending_migrations": [], "newest_capture": "2026-09-14"},
        "inference": {"status": "ok", "strategies": 38, "heroes": 54},
        "ui": {"heroes": [{}] * 54, "maps": [{}] * 30}})
    assert ok and any("54 heroes (1 announced, not yet playable)" in line for line in lines)
    ok, lines = orchestrator.verdict({"data": {"status": "ok", "state": "stale",
                                               "table_count": 42, "heroes": 53,
                                               "pending_migrations": ["099_future.sql"]},
                                      "inference": {"status": "ok", "strategies": 0},
                                      "ui": None})
    assert not ok
    assert any("behind the migrations (099_future.sql)" in line for line in lines)
    assert any("stale bind mount" in line for line in lines)
    assert any("board: not answering" in line for line in lines)


def test_the_verdict_waits_on_the_data_layers_state():
    """Ready is the state the data layer reports, db.psql.schema.state; an
    image older than the checkout reports none, and is not ready either."""
    served = {
        "inference": {"status": "ok", "strategies": 38, "heroes": 54},
        "ui": {"heroes": [{}] * 54, "maps": [{}] * 30}}
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
    with pytest.raises(RuntimeError, match="no claude CLI"):
        orchestrator.agents_command()


@pytest.mark.skipif(not os.path.exists(REFRESH_SKILL), reason="the skills are not in the image")
def test_the_allowlist_is_exactly_the_tools_the_refresh_skill_names():
    from db.mcp import tools
    with open(REFRESH_SKILL, encoding="utf-8") as handle:
        named = set(re.findall(r"`([a-z_]+)`", handle.read()))
    registered = {name for name, *_ in tools.REGISTRY}
    assert set(orchestrator.AGENT_TOOL_NAMES) == named & registered


def test_no_verb_means_the_whole_run_and_a_bad_verb_prints_the_usage(monkeypatch):
    seen = []
    monkeypatch.setattr(orchestrator, "run", lambda: seen.append("run") or 0)
    monkeypatch.setattr(orchestrator, "status", lambda: seen.append("status") or 0)
    assert orchestrator.main([]) == 0 and orchestrator.main(["status"]) == 0
    assert seen == ["run", "status"]
    with pytest.raises(SystemExit):
        orchestrator.main(["dance"])


def test_drafts_are_derived_on_the_host_then_the_stack_remirrors(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrator, "sh", lambda *a, **k: calls.append(("sh", a[-1])))
    monkeypatch.setattr(orchestrator, "mcp",
                        lambda name, args=None, **k: calls.append(("mcp", name)))
    orchestrator.derive_pending({"inference": {"strategies": 38, "pending": 0}})
    orchestrator.derive_pending({"inference": None})
    assert calls == []
    orchestrator.derive_pending({"inference": {"strategies": 39, "pending": 1}})
    assert calls == [("sh", "derive_strategies"), ("mcp", "load_authored")]


# --- the verbs, with docker and the network stubbed out --------------------------------

@pytest.fixture()
def stubbed(monkeypatch):
    """Every side effect of the orchestrator recorded instead of run."""
    calls = []
    healthy = {"data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54,
                        "announced": 1, "pending_migrations": [],
                        "newest_capture": "2026-09-14"},
               "inference": {"status": "ok", "strategies": 38, "heroes": 54, "pending": 0},
               "ui": {"heroes": [{}] * 54, "maps": [{}] * 30}}
    monkeypatch.setattr(orchestrator, "sh", lambda *a, **k: calls.append(("sh", *a)) or "")
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


def test_status_derives_pending_drafts_on_the_host(stubbed, capsys):
    calls, healthy = stubbed
    healthy["inference"]["pending"] = 2
    assert orchestrator.status() == 0
    assert any(c[0] == "sh" and "derive_strategies" in c for c in calls)
    assert ("mcp", "load_authored") in calls
    assert "sentry: ok" in capsys.readouterr().out


def test_refresh_test_down_and_main_dispatch(stubbed, capsys):
    calls, _ = stubbed
    assert orchestrator.refresh() == 0 and ("mcp", "sync_all") in calls
    assert orchestrator.test() == 0
    suite = next(c for c in calls if "pytest" in c)     # in the image, on the shipped playbook
    assert "COVERAGE_FILE=/tmp/.coverage" in suite and "COUNTRIX_STRATEGIES=" in suite
    assert orchestrator.down() == 0 and ("sh", "docker", "compose", "down") in calls
    assert orchestrator.main(["status"]) == 0
    with pytest.raises(SystemExit):
        orchestrator.main(["up", "status"])


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
