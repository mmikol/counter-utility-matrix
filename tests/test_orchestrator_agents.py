"""orchestrator.py's agents: the headless claude run on the refresh skill, its
allowlist of tools, and the drafts derived on the host against the stack's
database. The CLI and the stack are stubbed out."""

import os
import re

import pytest

import orchestrator

REFRESH_SKILL = os.path.join(orchestrator.ROOT, ".claude", "skills", "refresh", "SKILL.md")


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
    from door.mcp import tools
    with open(REFRESH_SKILL, encoding="utf-8") as handle:
        named = set(re.findall(r"`([a-z_]+)`", handle.read()))
    registered = set(tools.REGISTRY.names())
    assert set(orchestrator.AGENT_TOOL_NAMES) == named & registered


def test_drafts_are_derived_on_the_host_against_the_stacks_database(monkeypatch):
    """The derive runs through ./docker-db with .env's password, so its own
    mirror writes the stack's strategies table and no second mirror follows
    over the door."""
    import subprocess
    import sys
    calls = []
    monkeypatch.setattr(orchestrator, "sh", lambda *a, timeout, env=None: calls.append((a, env)))
    monkeypatch.setattr(orchestrator, "mcp",
                        lambda name, args=None, **k: pytest.fail("the door was called: %s" % name))
    monkeypatch.setattr(orchestrator, "dotenv", lambda: {"POSTGRES_PASSWORD": "pw"})
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    assert orchestrator.derive_pending({"inference": {"strategies": 38, "pending": 0}}) is False
    assert orchestrator.derive_pending({"inference": None}) is False
    assert calls == []
    assert orchestrator.derive_pending({"inference": {"strategies": 39, "pending": 1}}) is True
    [(args, env)] = calls
    assert args[0] == os.path.join(orchestrator.ROOT, "docker-db")
    assert args[-1] == "derive_strategies" and env["POSTGRES_PASSWORD"] == "pw"
    printed = subprocess.run(
        [args[0], sys.executable, "-c", "import os; print(os.environ['DATABASE_URL'])"],
        env=env, capture_output=True, text=True, timeout=60, check=True)
    assert printed.stdout.strip() == "postgresql://overwatch:pw@localhost:5433/overwatch"
