"""The data layer's door: the MCP server speaks the protocol over stdio and
its tools validate their arguments. The protocol tests spawn the real
server as a subprocess and need no database (tools/list and list_sources
read nothing); the tool tests need the built database."""

import json
import os
import subprocess
import sys

import pytest

from data.mcp import tools
from data.mcp.server import Server, Tool, ToolError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _talk(messages):
    proc = subprocess.Popen([sys.executable, "-m", "data.mcp"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate("\n".join(json.dumps(m) for m in messages) + "\n",
                                timeout=60)
    assert proc.returncode == 0, err
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_initialize_then_list_tools_over_stdio():
    replies = _talk([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ])
    assert replies[0]["id"] == 1
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert replies[0]["result"]["serverInfo"]["name"] == "overwatch-db"
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert {"pull_heroes", "pull_rates", "sync_all", "db_rebuild", "query",
            "facts", "infer", "evaluate", "board", "record", "load_playbook",
            "record_outcome", "tune", "fit_weights", "tuning_log"} <= names
    for t in replies[1]["result"]["tools"]:
        assert t["inputSchema"]["type"] == "object" and t["description"]
    assert replies[2] == {"jsonrpc": "2.0", "id": 3, "result": {}}


def test_tools_call_without_a_database_and_unknown_method():
    replies = _talk([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "list_sources", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "no/such/method"},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
    ])
    text = replies[0]["result"]["content"][0]["text"]
    assert "blizzard" in text and "wiki" in text and "counterpick" in text
    assert replies[0]["result"]["isError"] is False
    assert replies[1]["error"]["code"] == -32601
    uris = {r["uri"] for r in replies[2]["result"]["resources"]}
    assert "heuristic://coverage" in uris and "heuristic://tuning-log" in uris


def test_bad_json_is_a_parse_error_not_a_crash():
    proc = subprocess.Popen([sys.executable, "-m", "data.mcp"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    out, _ = proc.communicate("{not json\n" + json.dumps(
        {"jsonrpc": "2.0", "id": 9, "method": "ping"}) + "\n", timeout=60)
    lines = [json.loads(l) for l in out.splitlines() if l.strip()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["id"] == 9


def test_tool_refuses_unknown_and_missing_arguments():
    tool = Tool("t", "d", {"type": "object", "properties": {"a": {"type": "string"}},
                           "required": ["a"]}, lambda **kw: ("ok", kw))
    with pytest.raises(ToolError, match="unknown argument"):
        tool({"a": "x", "b": 1})
    with pytest.raises(ToolError, match="missing"):
        tool({})
    assert tool({"a": "x"}) == ("ok", {"a": "x"})


def test_server_reports_a_refused_tool_as_is_error():
    def refuse(**kw):
        raise ToolError("no")
    server = Server([Tool("t", "d", {"type": "object", "properties": {}}, refuse)])
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "t", "arguments": {}}})
    assert reply["result"]["isError"] is True


# --- the tools against the built database ------------------------------------

@pytest.fixture(scope="module")
def ctx(db):
    import psycopg
    return tools.Context(dsn=db.info.dsn if hasattr(db.info, "dsn") else
                         psycopg.conninfo.make_conninfo(**db.info.get_parameters()))


@pytest.mark.invariant
def test_query_is_read_only(ctx):
    text, data = tools.run_tool(ctx, "query", sql="select count(*) from heroes")
    assert data["rows"][0][0] > 40
    with pytest.raises(ToolError, match="read-only"):
        tools.run_tool(ctx, "query", sql="delete from heroes")
    with pytest.raises(ToolError, match="read-only"):
        tools.run_tool(ctx, "query", sql="select 1; drop table heroes")


@pytest.mark.invariant
def test_db_status_and_roster(ctx):
    _, status = tools.run_tool(ctx, "db_status")
    assert status["tables"] >= 38 and status["counts"]["heroes"] > 40
    _, roster = tools.run_tool(ctx, "roster")
    assert any(h["name"] == "Ana" and h["portrait"] for h in roster["heroes"])
    assert any(m["name"] == "King's Row" and m["mode"] == "Hybrid" for m in roster["maps"])


@pytest.mark.invariant
def test_facts_and_infer_through_the_tools(ctx):
    text, data = tools.run_tool(ctx, "facts", map="King's Row", red=["Zarya"], blue=["Ana"])
    assert data["count"] > 300 and text.startswith("[F1]")
    with pytest.raises(ToolError, match="unknown heroes"):
        tools.run_tool(ctx, "facts", red=["Goku"])
    text, data = tools.run_tool(ctx, "infer", map="King's Row", red=["Zarya"], blue=["Ana"])
    assert len(data["blue"]) == 6 and "Ana" in data["blue"]
    assert "optimal comp" in text


# --- the Streamable HTTP transport (the data-layer container's door) -----------

@pytest.fixture(scope="module")
def http_server():
    import socket
    import time
    import urllib.request
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen([sys.executable, "-m", "data.mcp", "--http", "127.0.0.1:%d" % port],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    base = "http://127.0.0.1:%d" % port
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/health", timeout=2)
            break
        except OSError:
            time.sleep(0.2)
    yield base
    proc.terminate()
    proc.wait(timeout=10)


def _post(base, payload, headers=None):
    import urllib.error
    import urllib.request
    request = urllib.request.Request(
        base + "/mcp", data=json.dumps(payload).encode("utf-8"),
        headers=dict({"Content-Type": "application/json",
                      "Accept": "application/json, text/event-stream"}, **(headers or {})))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            return response.status, dict(response.headers), json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        body = error.read()
        return error.code, dict(error.headers), json.loads(body) if body else None


def test_http_transport_initializes_lists_and_calls(http_server):
    status, headers, reply = _post(http_server, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}}})
    assert status == 200 and reply["result"]["serverInfo"]["name"] == "overwatch-db"
    assert headers.get("Mcp-Session-Id")
    status, _, reply = _post(http_server, {"jsonrpc": "2.0",
                                           "method": "notifications/initialized"})
    assert status == 202 and reply is None
    status, _, reply = _post(http_server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert status == 200 and any(t["name"] == "infer" for t in reply["result"]["tools"])
    status, _, reply = _post(http_server, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                           "params": {"name": "list_sources",
                                                      "arguments": {}}})
    assert status == 200 and "wiki" in reply["result"]["content"][0]["text"]


def test_http_transport_guards_get_origin_and_health(http_server):
    import urllib.error
    import urllib.request
    with pytest.raises(urllib.error.HTTPError) as blocked:
        urllib.request.urlopen(http_server + "/mcp", timeout=10)
    assert blocked.value.code == 405
    status, _, _ = _post(http_server, {"jsonrpc": "2.0", "id": 9, "method": "ping"},
                         {"Origin": "https://evil.example"})
    assert status == 403
    health = json.load(urllib.request.urlopen(http_server + "/health", timeout=10))
    assert health["status"] in ("ok", "degraded")
