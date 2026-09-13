"""orchestrator.py: the verdict logic is pure; the docker verbs are not exercised."""

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
    from inference import derive
    monkeypatch.setattr(derive, "cli", lambda: None)
    import pytest
    with pytest.raises(RuntimeError, match="no claude CLI"):
        orchestrator.agents_command()
