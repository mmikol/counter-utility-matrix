"""The door's entry point and in-process call: `python -m door.mcp list` and
`call`, the data container's /health, and ctx.call - the refresher's, the
shell's and the board's path - validated and audited like a call through
either door."""

import json

import pytest

from db import Refusal
from door.mcp import tools
from door.mcp.__main__ import _status, main


def test_the_entry_point_lists_tools_and_refuses_nonsense(capsys, tmp_path, monkeypatch):
    """Usage is 2, a refused call 1 with the reason on stderr; the strategies
    call reaches the wrapper, so its audit line lands in tmp_path."""
    monkeypatch.setenv("COUNTRIX_AUDIT", str(tmp_path / "audit.jsonl"))
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "db_status" in out and "infer" in out
    assert main(["bogus"]) == 2
    assert main(["call", "no_such_tool"]) == 1
    assert "error: no tool named 'no_such_tool'" in capsys.readouterr().err
    assert main(["call", "strategies", '{"bogus": 1}']) == 1
    assert "unknown argument(s) bogus" in capsys.readouterr().err
    assert main(["call", "metrics", "{not json"]) == 2
    assert main(["call", "metrics", "[1]"]) == 2
    assert "python -m door.mcp call" in capsys.readouterr().err


@pytest.mark.invariant
def test_the_entry_point_calls_a_tool(capsys, dsn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", dsn)
    assert main(["call", "db_status"]) == 0
    assert "tables" in capsys.readouterr().out


def test_health_is_degraded_when_the_database_is_out_of_reach_and_crashes_otherwise(
        tmp_path, monkeypatch):
    """The data container's /health answers degraded for every way the database
    can be out of reach, and nothing else: a bug in the tool still surfaces."""
    monkeypatch.setenv("COUNTRIX_AUDIT", str(tmp_path / "audit.jsonl"))
    status = _status(tools.Context(dsn="postgresql://nobody@127.0.0.1:9/nowhere"))
    reply = status()
    assert reply["status"] == "degraded" and reply["error"]

    def broken(ctx, name, /, **arguments):
        raise RuntimeError("a bug in db_status")
    monkeypatch.setattr(tools.Context, "call", broken)
    with pytest.raises(RuntimeError, match="a bug"):
        status()


def test_an_in_process_call_is_validated_against_the_tools_schema(tmp_path, monkeypatch):
    """The shell, the refresher and the board call through the same wrapper
    as either door, so a call the schema refuses never reaches the tool and
    is audited as refused, not as a crash."""
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("COUNTRIX_AUDIT", str(path))
    ctx = tools.Context(dsn="postgresql://nowhere")
    with pytest.raises(Refusal, match="strategies: unknown argument"):
        ctx.call("strategies", bogus=1)
    with pytest.raises(Refusal, match="reach: 'hero' must be string"):
        ctx.call("reach", hero=5)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [(e["tool"], e["ok"], "refused" in e) for e in lines] == [
        ("strategies", False, True), ("reach", False, True)]


def test_an_in_process_tool_call_leaves_one_audit_line(tmp_path, monkeypatch):
    """The sentry's window is the audit log, so the refresher's and the shell's
    path has to appear in it like a call through either door."""
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("COUNTRIX_AUDIT", str(path))
    ctx = tools.Context(dsn="postgresql://nobody@127.0.0.1:9/x")
    ctx.call("list_sources")
    with pytest.raises(tools.NoSuchToolError):
        ctx.call("no_such_tool")          # never reached a tool: no line
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [e["tool"] for e in lines] == ["list_sources"]
    assert lines[0]["transport"] == "in-process" and lines[0]["ok"] is True
    assert lines[0]["client"] is None and "ms" in lines[0]


def test_a_tool_argument_named_name_reaches_the_tool():
    """ctx.call takes the tool's name positionally, so add_strategy's own `name`
    argument is not swallowed by the call - it raised TypeError once."""
    with pytest.raises(tools.NoSuchToolError, match="no tool named 'no_such_tool'"):
        tools.Context(dsn="postgresql://nobody@127.0.0.1:9/x").call(
            "no_such_tool", name="Players play optimally")
