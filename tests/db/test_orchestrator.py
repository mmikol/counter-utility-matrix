"""orchestrator.py: the verdict, the dispatch, the agents' command and the
draft hand-off are pure; the docker verbs are not exercised."""

import pytest

import orchestrator


def test_verdict_reads_the_three_health_replies():
    ok, lines = orchestrator.verdict({
        "data": {"status": "ok", "tables": 42, "heroes": 53, "outcomes": 2,
                 "pending_migrations": [], "newest_capture": "2026-09-13"},
        "inference": {"status": "ok", "strategies": 38, "heroes": 53},
        "ui": {"heroes": [{}] * 53, "maps": [{}] * 30}})
    assert ok and any("rates captured 2026-09-13" in l for l in lines)
    ok, lines = orchestrator.verdict({"data": {"status": "ok", "tables": 42, "heroes": 53,
                                        "pending_migrations": ["009_outcomes.sql"]},
                               "inference": {"status": "ok", "strategies": 0},
                               "ui": None})
    assert not ok
    assert any("behind the migrations" in l for l in lines)
    assert any("stale bind mount" in l for l in lines)
    assert any("board: not answering" in l for l in lines)


def test_health_urls_cover_every_served_layer():
    assert set(orchestrator.URLS) == {"data", "inference", "ui"}


def test_the_agents_run_is_headless_claude_on_the_refresh_skill(monkeypatch):
    command = orchestrator.agents_command(claude="/x/claude")
    assert command[:3] == ["/x/claude", "-p", "/refresh"]
    assert "--allowedTools" in command and orchestrator.AGENT_TOOLS in command
    assert "--no-session-persistence" in command and "--output-format" in command
    assert command[command.index("--tools") + 1] == "" and "--max-turns" in command
    allowed = set(orchestrator.AGENT_TOOLS.split(","))
    assert "mcp__counter-utility-matrix-docker__sync_all" in allowed
    assert "mcp__counter-utility-matrix__infer_strategy" in allowed
    assert "mcp__counter-utility-matrix-docker__query" in allowed      # read-only, its own login
    for never in ("add_strategy", "db_rebuild", "db_init", "db_migrate", "record", "record_outcome"):
        assert not any(t.endswith("__" + never) for t in allowed), never
    from inference import derive
    monkeypatch.setattr(derive, "cli", lambda: None)
    with pytest.raises(RuntimeError, match="no claude CLI"):
        orchestrator.agents_command()


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
    monkeypatch.setattr(orchestrator, "mcp", lambda name, args=None, **k: calls.append(("mcp", name)))
    orchestrator.derive_pending({"inference": {"strategies": 38, "pending": 0}})
    orchestrator.derive_pending({"inference": None})
    assert calls == []
    orchestrator.derive_pending({"inference": {"strategies": 39, "pending": 1}})
    assert calls == [("sh", "derive_strategies"), ("mcp", "load_authored")]


def test_a_signed_out_cli_skips_the_agents_run_instead_of_failing(monkeypatch, capsys):
    import subprocess
    monkeypatch.setattr(orchestrator, "agents_command", lambda: ["/x/claude", "-p", "/refresh"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, stdout="Not logged in · Please run /login\n", stderr=""))
    assert orchestrator.agents() == 0
    assert "not signed in" in capsys.readouterr().out
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 2, stdout="", stderr="boom"))
    assert orchestrator.agents() != 0
