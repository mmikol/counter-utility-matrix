"""orchestrator.py's verbs with docker, the network and the claude CLI stubbed
out: the dispatch, a command past its timeout, and each verb's calls - up,
status, refresh, test, down, agents and the whole run. The verdict is
tests/test_orchestrator_verdict.py's, the agents' fences
test_orchestrator_agents.py's, the HTTP helpers test_orchestrator_http.py's."""

import pytest

import orchestrator


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


# --- the verbs, with docker and the network stubbed out --------------------------------

@pytest.fixture()
def stubbed(monkeypatch):
    """Every side effect of the orchestrator recorded instead of run."""
    calls = []
    healthy = {
        "data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54,
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
