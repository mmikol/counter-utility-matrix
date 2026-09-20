"""The data layer's door: the MCP server speaks the protocol over stdio and
its tools validate their arguments. The protocol tests spawn the real
server as a subprocess and need no database (tools/list and list_sources
read nothing); the tool tests need the built database."""

import json
import subprocess
import sys

import pytest

from db import ROOT
from db.mcp import tools
from db.mcp.server import Server, Tool, ToolError


def _talk(messages):
    proc = subprocess.Popen([sys.executable, "-m", "db.mcp"], cwd=ROOT,
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
    assert replies[0]["result"]["serverInfo"]["name"] == "countrix"
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert {"pull_heroes", "pull_rates", "pull_seasons", "pull_synergies", "sync_all",
            "db_rebuild", "db_migrate", "query",
            "facts", "infer", "evaluate", "board", "strategies", "load_authored",
            "tune", "tuning_log", "metrics",
            "add_strategy", "infer_strategy", "derive_strategies", "db_docs"} <= names
    assert len(names) == len(tools.REGISTRY)      # every registered tool is served
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
    assert "blizzard" in text and "wiki" in text and "counterpick" not in text
    assert "pull_counters" in next(line for line in text.splitlines() if line.startswith("wiki"))
    assert replies[0]["result"]["isError"] is False
    assert replies[1]["error"]["code"] == -32601
    uris = {r["uri"] for r in replies[2]["result"]["resources"]}
    assert "strategy://queue-allows-two-tanks" in uris and "strategy://tuning-log" in uris


def test_bad_json_is_a_parse_error_not_a_crash():
    proc = subprocess.Popen([sys.executable, "-m", "db.mcp"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    out, _ = proc.communicate("{not json\n" + json.dumps(
        {"jsonrpc": "2.0", "id": 9, "method": "ping"}) + "\n", timeout=60)
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
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
def ctx(db, dsn):
    return tools.Context(dsn=dsn)


@pytest.mark.invariant
def test_query_is_read_only(ctx):
    _text, data = tools.run_tool(ctx, "query", sql="select count(*) from heroes")
    assert data["rows"][0][0] > 40
    with pytest.raises(ToolError, match="read-only"):
        tools.run_tool(ctx, "query", sql="delete from heroes")
    with pytest.raises(ToolError, match="read-only"):
        tools.run_tool(ctx, "query", sql="select 1; drop table heroes")


@pytest.mark.invariant
def test_db_status_and_roster(ctx):
    _, status = tools.run_tool(ctx, "db_status")
    # 33: map_strategy went with counterpick.gg (migration 019)
    assert status["tables"] >= 33 and status["counts"]["heroes"] > 40
    assert status["counts"]["counters"] >= 100
    assert {s["source"] for s in status["snapshots"]} == {"blizzard"}
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


@pytest.mark.invariant
def test_a_compact_infer_names_the_silent_heuristics_and_fits_a_reply(ctx):
    board = {"map": "King's Row", "red": ["Zarya"], "blue": ["Ana"]}
    _, full = tools.run_tool(ctx, "infer", **board)
    text, data = tools.run_tool(ctx, "infer", compact=True, **board)
    assert data["blue"] == full["blue"] and data["score"] == full["score"]
    silent = sorted(c["id"] for c in full["contributions"]
                    if c["kind"] == "heuristic" and c["applies"] and not c["spread"])
    assert data["silent"] == silent
    assert data["idle"] == sum(1 for c in full["contributions"] if not c["applies"])
    assert len(data["largest"]) <= tools.COMPACT_TERMS
    assert len(text) + len(json.dumps(data)) < 10000


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
    proc = subprocess.Popen([sys.executable, "-m", "db.mcp", "--http", "127.0.0.1:%d" % port],
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
    assert status == 200 and reply["result"]["serverInfo"]["name"] == "countrix"
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


@pytest.mark.invariant
def test_db_migrate_is_idle_when_the_ledger_is_current(ctx):
    text, data = tools.run_tool(ctx, "db_migrate")
    assert data["applied"] == [] and text.startswith("db_migrate: applied 0")


# Neither of these touches the database, so they run without one (as CI does).

def test_metrics_tool_serves_the_vocabulary():
    text, data = tools.run_tool(tools.Context(dsn="postgresql://nowhere"), "metrics")
    assert "team.coverage_share" in data["metrics"] and "team.coverage_share" in data["numeric"]
    assert "map.side" in data["text"] and "map.side" not in data["numeric"]
    assert text.splitlines()[0].startswith("team.")


def test_derive_strategies_is_idle_with_nothing_pending():
    text, data = tools.run_tool(tools.Context(dsn="postgresql://nowhere"), "derive_strategies")
    assert data["skipped"] == "nothing pending" and "nothing pending" in text


# --- the door's guards: token, size, rate, audit ------------------------------------------

def _http_server(tmp_path, token=None, rate_limit=120):
    import threading

    from db.mcp.server import HttpServer
    mcp = Server(tools.build(tools.Context(dsn="postgresql://nowhere")), None,
                 transport="http", audit_path=str(tmp_path / "audit.jsonl"))
    httpd = HttpServer(("127.0.0.1", 0), mcp, lambda: {"status": "ok"}, token=token,
                       rate_limit=rate_limit)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


def _knock(url, body, headers=None):
    import urllib.error
    import urllib.request
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    request = urllib.request.Request(url + "/mcp", data=data, headers=dict(
        {"Content-Type": "application/json"}, **(headers or {})))
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def test_the_door_requires_its_token_when_one_is_set(tmp_path):
    httpd, url = _http_server(tmp_path, token="s3cret")
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "list_sources", "arguments": {}}}
    assert _knock(url, call)[0] == 401
    assert _knock(url, call, {"Authorization": "Bearer wrong"})[0] == 401
    code, reply = _knock(url, call, {"Authorization": "Bearer s3cret"})
    assert code == 200 and reply["result"]["isError"] is False
    httpd.shutdown()


def test_the_door_refuses_huge_bodies_and_rate_limits_a_client_and_audits_every_call(tmp_path):
    httpd, url = _http_server(tmp_path, rate_limit=3)
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "list_sources", "arguments": {}}}
    assert _knock(url, b"x" * ((1 << 20) + 1))[0] == 413
    codes = [_knock(url, call, {"Mcp-Session-Id": "one"})[0] for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert _knock(url, call, {"Mcp-Session-Id": "two"})[0] == 429     # the budget is the host's
    batch = [dict(call, id=i) for i in range(21)]
    assert _knock(url, batch)[0] == 413
    lines = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert len(lines) == 3 and all(line["tool"] == "list_sources" and line["ok"] for line in lines)
    assert lines[0]["transport"] == "http" and lines[0]["client"].startswith("http:127.0.0.1/one")
    assert set(lines[0]) >= {"t", "args", "ms"}
    httpd.shutdown()


def test_query_refuses_file_and_server_reaching_sql_before_connecting():
    nowhere = tools.Context(dsn="postgresql://nowhere")
    for sql in ("select pg_read_file('/etc/passwd')", "select * from pg_ls_dir('.')",
                "COPY heroes TO PROGRAM 'id'", "select pg_sleep(10)"):
        with pytest.raises(ToolError, match=r"refuses|read-only"):
            tools.run_tool(nowhere, "query", sql=sql)


@pytest.mark.invariant
def test_query_runs_as_the_reader_role(ctx):
    _text, data = tools.run_tool(ctx, "query", sql="select current_user, count(*) from heroes")
    assert data["rows"][0][0] == "matrix_reader" and data["rows"][0][1] > 0


# --- the entry point ------------------------------------------------------------------

def test_the_entry_point_lists_tools_and_refuses_nonsense(capsys):
    from db.mcp.__main__ import main
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "db_status" in out and "infer" in out
    with pytest.raises(SystemExit):
        main(["bogus"])
    with pytest.raises(SystemExit):
        main(["call", "no_such_tool"])


@pytest.mark.invariant
def test_the_entry_point_calls_a_tool(capsys, dsn, monkeypatch):
    from db.mcp.__main__ import main
    monkeypatch.setenv("DATABASE_URL", dsn)
    assert main(["call", "db_status"]) == 0
    assert "tables" in capsys.readouterr().out


def test_a_tool_argument_named_name_reaches_the_tool():
    """run_tool takes the tool's name positionally, so add_strategy's own `name`
    argument is not swallowed by the call - it raised TypeError once."""
    with pytest.raises(KeyError):
        tools.run_tool(tools.Context(dsn="postgresql://nobody@127.0.0.1:9/x"), "no_such_tool",
                       name="Players play optimally")
