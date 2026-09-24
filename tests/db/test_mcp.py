"""The data layer's door: the MCP server speaks the protocol over stdio and
its tools validate their arguments. The protocol tests spawn the real
server as a subprocess and need no database (tools/list and list_sources
read nothing); the tool tests need the built database."""

import contextlib
import datetime
import decimal
import json
import os
import shutil
import subprocess
import sys

import pytest

from db import ROOT, Refusal
from db.mcp import layers, lifecycle, playbook, pulls, tools
from db.mcp.registry import Registry
from db.mcp.server import Server, Tool
from inference import catalog, tune
from tests.inference import FIXTURE_PLAYBOOK


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
    assert "strategy://tuning-log" in uris


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
    tool = Tool("t", "d", {"type": "object", "required": ["a"], "properties": {
        "a": {"type": "string"}, "n": {"type": "integer"}, "x": {"type": "number"},
        "names": {"type": "array", "items": {"type": "string"}},
        "side": {"type": "string", "enum": ["attack", "defense"]}, "any": {}}},
        lambda **kw: ("ok", kw))
    with pytest.raises(Refusal, match="unknown argument"):
        tool({"a": "x", "b": 1})
    with pytest.raises(Refusal, match="missing"):
        tool({})
    assert tool({"a": "x"}) == ("ok", {"a": "x"})
    # a value is checked as well as a name: the type, an array's items, the enum
    for arguments, named, wanted in (
            ({"a": 5}, "'a'", "must be string"),
            ({"a": None}, "'a'", "must be string"),
            ({"a": "x", "n": True}, "'n'", "must be integer"),      # a bool is no integer
            ({"a": "x", "n": 1.5}, "'n'", "must be integer"),
            ({"a": "x", "x": False}, "'x'", "must be number"),
            ({"a": "x", "names": ["Ana", 3]}, "'names'", "must be array of string"),
            ({"a": "x", "side": "sideways"}, "'side'", "must be one of 'attack', 'defense'")):
        with pytest.raises(Refusal) as refused:
            tool(arguments)
        assert str(refused.value) == "t: %s %s" % (named, wanted)
    passing = {"a": "x", "n": 2, "x": 2, "names": ("Ana",), "side": "attack", "any": None}
    assert tool(passing) == ("ok", passing)


def test_server_reports_a_refused_tool_as_is_error(tmp_path):
    """Every Refusal is the caller's error: the door answers it isError and
    audits it as refused - a TuneError as much as a Refusal raised plainly."""
    def refuse(**kw):
        raise Refusal("no")

    def refuse_a_tune(**kw):
        raise tune.TuneError("no strategy 'x'")
    empty = {"type": "object", "properties": {}}
    audit = tmp_path / "audit.jsonl"
    server = Server([Tool("t", "d", empty, refuse), Tool("tuned", "d", empty, refuse_a_tune)],
                    audit_path=str(audit))
    for name, said in (("t", "no"), ("tuned", "no strategy 'x'")):
        reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": name, "arguments": {}}})
        assert reply["result"]["isError"] is True
        assert reply["result"]["content"][0]["text"] == said
    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [(e["tool"], e["refused"]) for e in lines] == [("t", "no"),
                                                         ("tuned", "no strategy 'x'")]
    assert not any(e.get("crashed") for e in lines)


def test_a_fault_inside_a_tool_is_internal_and_logged_not_a_bad_parameter(tmp_path):
    """INVALID_PARAMS is for what the request got wrong. A KeyError raised deep
    inside a tool is the server's own fault: it reads as INTERNAL and leaves a
    traceback in the log."""
    def crash(**kw):
        raise KeyError("a lookup inside the tool")
    logged = []
    server = Server([Tool("t", "d", {"type": "object", "properties": {}}, crash)],
                    log=logged.append, audit_path=str(tmp_path / "audit.jsonl"))
    call = lambda method, params: server.handle(                      # noqa: E731
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    fault = call("tools/call", {"name": "t", "arguments": {}})["error"]
    assert fault["code"] == -32603 and "KeyError" in fault["message"]
    assert logged and "Traceback" in logged[0]
    assert call("tools/call", {})["error"] == {
        "code": -32602, "message": "missing parameter 'name'"}
    assert call("tools/call", {"name": "nope"})["error"] == {
        "code": -32602, "message": "no tool named 'nope'"}
    assert call("tools/call", {"name": "t", "arguments": [1]})["error"] == {
        "code": -32602, "message": "arguments must be an object"}
    assert call("resources/read", {})["error"]["code"] == -32602
    assert call("resources/read", {"uri": "strategy://x"})["error"]["code"] == -32602


def test_the_strategy_resources_answer_an_unknown_uri_as_a_bad_parameter(tmp_path):
    """The one implementation of the resources a server serves: an id no file
    holds is a bad parameter, and a strategy's uri reads back its file."""
    server = Server([], tools.StrategyResources(), log=lambda message: None,
                    audit_path=str(tmp_path / "audit.jsonl"))

    def read(uri):
        return server.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/read",
                              "params": {"uri": uri}})
    missing = read("strategy://nope")["error"]
    assert missing["code"] == -32602 and missing["message"].startswith("no resource at")
    first = catalog.load()[0]
    assert read("strategy://" + first.id)["result"]["contents"][0]["text"] == first.raw


def test_a_broken_playbook_is_a_server_fault_at_the_door(tmp_path, monkeypatch):
    """A playbook that does not load is the operator's to fix, not the caller's:
    every tool and resource that reads it answers INTERNAL with the catalog's
    own message, logs the traceback and is audited as crashed."""
    empty = tmp_path / "playbook"
    empty.mkdir()
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(empty))
    logged = []
    audit = tmp_path / "audit.jsonl"
    server = Server(tools.build(tools.Context(dsn="postgresql://nowhere")),
                    tools.StrategyResources(), log=logged.append, audit_path=str(audit))
    for method, params in (("tools/call", {"name": "strategies", "arguments": {}}),
                           ("resources/list", {})):
        fault = server.handle({"jsonrpc": "2.0", "id": 1, "method": method,
                               "params": params})["error"]
        assert fault["code"] == -32603
        assert fault["message"].startswith("CatalogError: no strategies in")
    assert logged and all("Traceback" in entry for entry in logged)
    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["tool"] == "strategies" and lines[0]["crashed"] is True


# --- the tools against the built database ------------------------------------

@pytest.fixture(scope="module")
def ctx(db, dsn):
    return tools.Context(dsn=dsn)


@pytest.mark.invariant
def test_query_is_read_only(ctx):
    _text, data = tools.run_tool(ctx, "query", sql="select count(*) from heroes")
    assert data["rows"][0][0] > 40
    text, data = tools.run_tool(ctx, "query", sql="select generate_series(1, 300)")
    assert len(data["rows"]) == 200 and data["truncated"] is True
    assert text.endswith("\n(truncated: 200 rows shown)")
    _text, data = tools.run_tool(ctx, "query", sql="select generate_series(1, 200)")
    assert len(data["rows"]) == 200 and data["truncated"] is False
    with pytest.raises(Refusal, match="read-only"):
        tools.run_tool(ctx, "query", sql="delete from heroes")
    with pytest.raises(Refusal, match="read-only"):
        tools.run_tool(ctx, "query", sql="select 1; drop table heroes")
    # what Postgres rejects is the caller's to fix too, answered in its words
    with pytest.raises(Refusal, match='query: column "nosuch" does not exist'):
        tools.run_tool(ctx, "query", sql="select nosuch from heroes")


@pytest.mark.invariant
def test_db_status_and_roster(ctx):
    text, status = tools.run_tool(ctx, "db_status")
    # 33: map_strategy went with counterpick.gg (migration 019)
    assert status["table_count"] >= 33 and status["counts"]["heroes"] > 40
    assert status["state"] == "current" and "state: current" in text
    assert status["counts"]["counters"] >= 100
    assert {s["source"] for s in status["snapshots"]} == {"blizzard"}
    _, roster = tools.run_tool(ctx, "roster")
    assert any(h["name"] == "Ana" and h["portrait"] for h in roster["heroes"])
    assert any(m["name"] == "King's Row" and m["mode"] == "Hybrid" for m in roster["maps"])


@pytest.mark.invariant
def test_facts_and_infer_through_the_tools(ctx):
    text, data = tools.run_tool(ctx, "facts", map="King's Row", red=["Zarya"], blue=["Ana"])
    assert data["count"] > 300 and text.startswith("[F1]")
    with pytest.raises(Refusal, match="unknown heroes"):
        tools.run_tool(ctx, "facts", red=["Goku"])
    with pytest.raises(Refusal, match="unknown heroes"):
        tools.run_tool(ctx, "reach", hero="Nosuchhero")
    text, data = tools.run_tool(ctx, "infer", map="King's Row", red=["Zarya"], blue=["Ana"])
    assert len(data["blue"]) == 6 and "Ana" in data["blue"]
    assert "optimal comp" in text


@pytest.mark.invariant
def test_a_compact_infer_names_the_silent_heuristics_and_fits_a_reply(ctx):
    board = {"map": "King's Row", "red": ["Zarya"], "blue": ["Ana"]}
    _, full = tools.run_tool(ctx, "infer", **board)
    text, data = tools.run_tool(ctx, "infer", compact=True, **board)
    assert data["blue"] == full["blue"] and data["score"] == full["score"]
    silent = sorted(c["id"] for c in full["contributions"] if c.get("spread") is False)
    assert data["silent"] == silent
    assert data["idle"] == sum(1 for c in full["contributions"] if not c["applies"])
    assert data["terms"] == len(full["contributions"]) and "strategies" not in data
    assert len(data["largest"]) <= layers.COMPACT_TERMS
    assert len(text) + len(json.dumps(data)) < 10000


# --- the Streamable HTTP transport (the data-layer container's door) -----------

@pytest.fixture(scope="module")
def http_server(tmp_path_factory):
    """The server over HTTP on a free port, once it answers /health. A child
    that exits first, or never answers, fails the fixture with its own
    stderr, which goes to a file: a pipe nobody reads fills and blocks it."""
    import socket
    import time
    import urllib.request
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    base = "http://127.0.0.1:%d" % port
    log = tmp_path_factory.mktemp("mcp_http") / "stderr.log"
    with log.open("wb") as err:
        proc = subprocess.Popen(
            [sys.executable, "-m", "db.mcp", "--http", "127.0.0.1:%d" % port],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=err)
        try:
            # a cold pgserver boots behind /health
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    pytest.fail("the mcp http server exited with %d before answering /health:\n%s"
                                % (proc.returncode,
                                   log.read_text(encoding="utf-8", errors="replace")))
                try:
                    with urllib.request.urlopen(base + "/health", timeout=2):
                        break
                except OSError:
                    time.sleep(0.2)
            else:
                pytest.fail("the mcp http server did not answer /health within 30 s:\n%s"
                            % log.read_text(encoding="utf-8", errors="replace"))
            yield base
        finally:
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
    if health["status"] == "ok":
        assert health["state"] in ("empty", "stale", "unfilled", "current")
    # a rebound page sends no Origin on a GET, but it names its own host
    with pytest.raises(urllib.error.HTTPError) as foreign:
        urllib.request.urlopen(urllib.request.Request(
            http_server + "/health", headers={"Host": "evil.example"}), timeout=10)
    assert foreign.value.code == 403

    def delete(path="/mcp", headers=None):
        request = urllib.request.Request(http_server + path, method="DELETE",
                                         headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    assert delete() == 200                                   # ends a session it never kept
    assert delete(headers={"Origin": "https://evil.example"}) == 403
    assert delete("/nope") == 404


@pytest.mark.invariant
def test_db_migrate_is_idle_when_the_ledger_is_current(ctx):
    text, data = tools.run_tool(ctx, "db_migrate")
    assert data["applied"] == [] and text.startswith("db_migrate: applied 0")


# None of these touches the database, so they run without one (as CI does).

def test_readiness_is_the_first_unmet_condition(monkeypatch):
    """One definition of ready for the entrypoint, compose, /health and the
    orchestrator: no tables, then a pending migration, then no heroes."""
    from db.psql import schema

    class Rows:
        def __init__(self, n):
            self.n = n

        def fetchone(self):
            return (self.n,)

    class Connection:
        def __init__(self, heroes):
            self.heroes = heroes

        def execute(self, sql, params=None):
            assert "heroes" in sql
            return Rows(self.heroes)

    def board(tables, pending, heroes):
        monkeypatch.setattr(schema, "table_count", lambda cx: tables)
        monkeypatch.setattr(schema, "pending", lambda cx: pending)
        return schema.state(Connection(heroes))

    assert board(0, ["001_initial_schema.sql"], 0) == "empty"
    assert board(35, ["099_future.sql"], 0) == "stale"
    assert board(35, ["099_future.sql"], 54) == "stale"
    assert board(35, [], 0) == "unfilled"
    assert board(35, [], 54) == "current"


def test_the_probe_exits_one_when_the_database_never_answers(monkeypatch, capsys):
    from db.psql import schema
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:9/nowhere")
    monkeypatch.setattr(schema, "CONNECT_TRIES", 2)
    monkeypatch.setattr(schema.time, "sleep", lambda seconds: None)
    assert schema.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "never became reachable" in captured.err


def test_health_is_degraded_when_the_database_is_out_of_reach_and_crashes_otherwise(
        tmp_path, monkeypatch):
    """The data container's /health answers degraded for every way the database
    can be out of reach, and nothing else: a bug in the tool still surfaces."""
    from db.mcp.__main__ import _status
    monkeypatch.setenv("COUNTRIX_AUDIT", str(tmp_path / "audit.jsonl"))
    status = _status(tools.Context(dsn="postgresql://nobody@127.0.0.1:9/nowhere"))
    reply = status()
    assert reply["status"] == "degraded" and reply["error"]

    def broken(ctx, name, /, **arguments):
        raise RuntimeError("a bug in db_status")
    monkeypatch.setattr(tools, "run_tool", broken)
    with pytest.raises(RuntimeError, match="a bug"):
        status()


def test_metrics_tool_serves_the_vocabulary():
    text, data = tools.run_tool(tools.Context(dsn="postgresql://nowhere"), "metrics")
    assert "team.coverage_share" in data["metrics"] and "team.coverage_share" in data["numeric"]
    assert "map.side" in data["text"] and "map.side" not in data["numeric"]
    assert text.splitlines()[0].startswith("team.")


def test_derive_strategies_is_idle_with_nothing_pending():
    text, data = tools.run_tool(tools.Context(dsn="postgresql://nowhere"), "derive_strategies")
    assert data["skipped"] == "nothing pending" and "nothing pending" in text
    assert data["deferred"] == 0


def test_every_playbook_write_mirrors_the_catalog_once(tmp_path, monkeypatch):
    """tune, add_strategy and infer_strategy each reload the strategies table
    once, after the write; derive_strategies with nothing derived connects to
    nothing."""
    for name in catalog.strategy_files(FIXTURE_PLAYBOOK):
        shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))
    monkeypatch.setenv("COUNTRIX_AUDIT", str(tmp_path / "audit.jsonl"))
    mirrored = []
    monkeypatch.setattr(catalog, "mirror", lambda cx, cat, directory=None: mirrored.append(
        (cx, len(cat))))

    class Offline(tools.Context):
        def connect(self):
            return contextlib.nullcontext("cx")
    ctx = Offline(dsn="postgresql://nowhere")
    heuristic = next(h for h in catalog.load() if h.kind == "heuristic")
    files = len(catalog.strategy_files(str(tmp_path)))
    tools.run_tool(ctx, "tune", id=heuristic.id, field="weight", value=3, reason="a test")
    assert mirrored == [("cx", files)]
    tools.run_tool(ctx, "add_strategy", id="a-draft", name="A draft", kind="heuristic",
                   body="Prose to infer from.", reason="a test")
    assert mirrored[1:] == [("cx", files + 1)]            # the new file is in the mirror
    tools.run_tool(ctx, "infer_strategy", id="a-draft", reason="a test",
                   metric=heuristic.metric, direction="maximize", weight=1)
    assert len(mirrored) == 3
    assert not [h.id for h in catalog.load() if h.pending]
    _, data = tools.run_tool(ctx, "derive_strategies")
    assert data["derived"] == [] and len(mirrored) == 3


def test_a_board_tool_hands_its_function_one_draft(tmp_path, monkeypatch):
    """The board tools share BOARD's five properties, first and in order, and
    each function gets them as one Draft: tuples, with what the call left out
    empty."""
    from ui.facts import board_facts, tables
    from ui.facts.draft import Draft
    monkeypatch.setenv("COUNTRIX_AUDIT", str(tmp_path / "audit.jsonl"))
    seen = []

    class Stub:
        def to_dict(self):
            return {}

        def rendered(self):
            return ""

    class Offline(tools.Context):
        def connect(self):
            return contextlib.nullcontext("cx")
    monkeypatch.setattr(tables, "load", lambda cx: None)
    monkeypatch.setattr(board_facts, "generate", lambda world, draft: seen.append(draft) or Stub())
    tools.run_tool(Offline(dsn="postgresql://nowhere"), "facts", map="Ilios", red=["Ana"],
                   bans=["Mei"])
    assert seen == [Draft("Ilios", ("Ana",), (), ("Mei",), "")]
    for name in ("facts", "infer", "evaluate", "board"):
        assert list(tools.REGISTRY.get(name).schema["properties"])[:5] == list(layers.BOARD)
    assert tools.REGISTRY.get("evaluate").schema["required"] == ["blue"]


def test_the_registry_lists_the_families_in_the_stated_order():
    families = (pulls.TOOLS, lifecycle.TOOLS, layers.TOOLS, playbook.TOOLS)
    assert tools.REGISTRY.names() == [n for family in families for n in family.names()]
    assert tools.Context.tools is tools.REGISTRY


def test_a_registry_refuses_a_tool_name_twice():
    registry = Registry()

    @registry.tool("twice", "the first")
    def first(ctx):
        return "first", {}
    with pytest.raises(ValueError, match="'twice'"):
        @registry.tool("twice", "the second")
        def second(ctx):
            return "second", {}
    assert registry.names() == ["twice"] and registry.get("twice").fn is first


# --- the door's guards: token, size, rate, audit ------------------------------------------

def _http_server(tmp_path, token=None, rate_limit=120):
    import threading

    from db.mcp.server import HttpServer
    mcp = Server(tools.build(tools.Context(dsn="postgresql://nowhere")), None,
                 audit_path=str(tmp_path / "audit.jsonl"))
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


def test_a_missing_content_length_is_refused_as_required(tmp_path):
    """A POST with no Content-Length, or one that is not a number, is told so
    - not answered as bad JSON after reading an empty body. urllib always sets
    the header, so the requests are built by hand."""
    import http.client
    from urllib.parse import urlparse
    httpd, url = _http_server(tmp_path)
    address = urlparse(url)
    for length in (None, "abc"):
        connection = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
        connection.putrequest("POST", "/mcp")
        connection.putheader("Content-Type", "application/json")
        if length is not None:
            connection.putheader("Content-Length", length)
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 400
        assert "Content-Length" in json.loads(response.read())["error"]
        connection.close()
    httpd.shutdown()


def test_query_refuses_file_and_server_reaching_sql_before_connecting():
    nowhere = tools.Context(dsn="postgresql://nowhere")
    for sql in ("select pg_read_file('/etc/passwd')", "select * from pg_ls_dir('.')",
                "COPY heroes TO PROGRAM 'id'", "select pg_sleep(10)"):
        with pytest.raises(Refusal, match=r"refuses|read-only"):
            tools.run_tool(nowhere, "query", sql=sql)
    long = "select '%s'" % ("x" * (lifecycle.MAX_SQL_CHARS - 8))       # one character over
    assert len(long) == lifecycle.MAX_SQL_CHARS + 1
    with pytest.raises(Refusal, match="too long"):
        tools.run_tool(nowhere, "query", sql=long)


def test_a_query_cell_arrives_as_json():
    """A date as ISO text, an array or JSONB cell as JSON all the way down, and
    anything JSON has no type for as its text."""
    day = datetime.date(2026, 9, 24)
    assert lifecycle._cell(day) == "2026-09-24"
    assert lifecycle._cell(datetime.datetime(2026, 9, 24, 5, 0)) == "2026-09-24T05:00:00"
    assert lifecycle._cell([1, [day, "x"], None]) == [1, ["2026-09-24", "x"], None]
    assert lifecycle._cell({"when": day, 3: (True, 1.5)}) == {"when": "2026-09-24",
                                                         "3": [True, 1.5]}
    assert lifecycle._cell(decimal.Decimal("0.515")) == "0.515"


def test_a_query_page_says_truncated_exactly_when_a_row_is_left_out():
    """Past MAX_ROWS rows, or past the byte budget; never at exactly MAX_ROWS."""
    rows, truncated = lifecycle._page([(n,) for n in range(lifecycle.MAX_ROWS + 1)])
    assert len(rows) == lifecycle.MAX_ROWS and truncated is True
    rows, truncated = lifecycle._page([(n,) for n in range(lifecycle.MAX_ROWS)])
    assert len(rows) == lifecycle.MAX_ROWS and truncated is False
    # each cell is cut to MAX_CELL characters and an ellipsis before the budget
    # counts it: a row of 300 is about 600 KB, so the second row spends the MiB
    wide = ["x" * 5000] * 300
    rows, truncated = lifecycle._page([wide, wide, wide])
    assert len(rows) == 1 and truncated is True
    assert {len(cell) for cell in rows[0]} == {lifecycle.MAX_CELL + 1}


@pytest.mark.invariant
def test_query_runs_as_the_reader_role(ctx):
    _text, data = tools.run_tool(ctx, "query", sql="select current_user, count(*) from heroes")
    assert data["rows"][0][0] == "matrix_reader" and data["rows"][0][1] > 0


# --- the entry point ------------------------------------------------------------------

def test_the_entry_point_lists_tools_and_refuses_nonsense(capsys, tmp_path, monkeypatch):
    """Usage is 2, a refused call 1 with the reason on stderr; the strategies
    call reaches the wrapper, so its audit line lands in tmp_path."""
    from db.mcp.__main__ import main
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
    assert "python -m db.mcp call" in capsys.readouterr().err


@pytest.mark.invariant
def test_the_entry_point_calls_a_tool(capsys, dsn, monkeypatch):
    from db.mcp.__main__ import main
    monkeypatch.setenv("DATABASE_URL", dsn)
    assert main(["call", "db_status"]) == 0
    assert "tables" in capsys.readouterr().out


def test_an_in_process_call_is_validated_against_the_tools_schema(tmp_path, monkeypatch):
    """The shell, the refresher and the board call through the same wrapper
    as either door, so a call the schema refuses never reaches the tool and
    is audited as refused, not as a crash."""
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("COUNTRIX_AUDIT", str(path))
    ctx = tools.Context(dsn="postgresql://nowhere")
    with pytest.raises(Refusal, match="strategies: unknown argument"):
        tools.run_tool(ctx, "strategies", bogus=1)
    with pytest.raises(Refusal, match="reach: 'hero' must be string"):
        tools.run_tool(ctx, "reach", hero=5)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [(e["tool"], e["ok"], "refused" in e) for e in lines] == [
        ("strategies", False, True), ("reach", False, True)]


def test_an_in_process_tool_call_leaves_one_audit_line(tmp_path, monkeypatch):
    """The sentry's window is the audit log, so the refresher's and the shell's
    path has to appear in it like a call through either door."""
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("COUNTRIX_AUDIT", str(path))
    ctx = tools.Context(dsn="postgresql://nobody@127.0.0.1:9/x")
    tools.run_tool(ctx, "list_sources")
    with pytest.raises(tools.NoSuchToolError):
        tools.run_tool(ctx, "no_such_tool")          # never reached a tool: no line
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [e["tool"] for e in lines] == ["list_sources"]
    assert lines[0]["transport"] == "in-process" and lines[0]["ok"] is True
    assert lines[0]["client"] is None and "ms" in lines[0]


def test_an_audit_line_that_cannot_be_written_is_noted_on_stderr_and_not_raised(
        tmp_path, capsys):
    """The door stays open when its log fails, and says so where the operator
    looks - stderr, never stdout, which over stdio is the wire."""
    from db.mcp.server import audit
    audit({"tool": "t"}, str(tmp_path))                 # a directory is no file to append to
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("countrix mcp: the audit log %s was not written: " % tmp_path)


def test_a_tool_argument_named_name_reaches_the_tool():
    """run_tool takes the tool's name positionally, so add_strategy's own `name`
    argument is not swallowed by the call - it raised TypeError once."""
    with pytest.raises(tools.NoSuchToolError, match="no tool named 'no_such_tool'"):
        tools.run_tool(tools.Context(dsn="postgresql://nobody@127.0.0.1:9/x"), "no_such_tool",
                       name="Players play optimally")
