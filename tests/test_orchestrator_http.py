"""orchestrator.py's helpers over the network and the host: the .env file and
the token it holds, the sentry's line, and a tool call posted to the door -
its answer, its refusal, and no answer at all. urllib is stubbed out."""

import json

import pytest

import orchestrator


def test_dotenv_token_sentry_line_and_the_http_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "ROOT", str(tmp_path))
    monkeypatch.setattr(orchestrator.sentry, "REPORT_PATH", str(tmp_path / "sentry.json"))
    assert orchestrator.dotenv() == {} and orchestrator.sentry_line() is None
    (tmp_path / ".env").write_text("# a comment\nCOUNTRIX_MCP_TOKEN='t0k'\nX=1\n")
    monkeypatch.delenv("COUNTRIX_MCP_TOKEN", raising=False)
    assert orchestrator.dotenv() == {"COUNTRIX_MCP_TOKEN": "t0k", "X": "1"}
    assert orchestrator.token() == "t0k"
    (tmp_path / ".env").unlink()
    (tmp_path / ".env").mkdir()                   # there, and unreadable: said, not skipped
    with pytest.raises(IsADirectoryError):
        orchestrator.dotenv()
    (tmp_path / "sentry.json").write_text(json.dumps({
        "ok": False, "checked_at": "t", "quarantined": ["x.md"], "flags": ["f1"],
        "calls_last_minute": 4}))
    line = orchestrator.sentry_line()
    assert "FLAGS" in line and "quarantined x.md" in line and "1 flag(s): f1" in line
    (tmp_path / "sentry.json").write_text(json.dumps({"ok": True, "checked_at": "t"}))
    assert orchestrator.sentry_line() is None          # a report short of a field says nothing
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
        status = 200

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
        status = 200

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
