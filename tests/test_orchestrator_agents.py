"""orchestrator.py's agents: the headless claude run on the refresh skill, its
allowlist of tools, and the drafts derived on the host before the stack
remirrors them. The CLI and the stack are stubbed out."""

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
