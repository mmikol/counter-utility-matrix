"""The door speaks the protocol: the real server spawned over
stdio, and the server's dispatch - the schema check every call passes, a
refusal answered as the caller's error, a fault as the server's, the
strategy resources, and the audit line a call leaves even when the log
cannot be written. None of it needs a database (tools/list and
list_sources read nothing). This module holds the tool set a session sees.
The HTTP door, the tools themselves, the registry and the entry point have
modules of their own (test_mcp_http, test_mcp_tools, test_mcp_registry,
test_mcp_entry)."""

import io
import json
import os
import subprocess
import sys

import pytest

from db import RAW_DIR, ROOT, Refusal
from door.mcp import stdio, tools
from door.mcp.audit import audit, audited, default_audit_path
from door.mcp.schema import Tool, tool_schema
from door.mcp.server import Server
from inference import catalog, tune


def _talk(messages):
    proc = subprocess.Popen([sys.executable, "-m", "door.mcp"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate("\n".join(json.dumps(m) for m in messages) + "\n",
                                timeout=60)
    assert proc.returncode == 0, err
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_initialize_then_list_tools_over_stdio():
    replies = _talk([
        {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
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
        {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
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
    proc = subprocess.Popen([sys.executable, "-m", "door.mcp"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate("{not json\n" + json.dumps(
        {"jsonrpc": "2.0", "id": 9, "method": "ping"}) + "\n", timeout=60)
    assert proc.returncode == 0, err          # a server that died says why
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["id"] == 9


def test_a_stdio_call_is_audited_under_the_process_that_launched_it(tmp_path):
    """Over stdio the caller is the host process that launched the server,
    named by its pid."""
    path = tmp_path / "audit.jsonl"
    server = Server([Tool("t", "d", tool_schema(), lambda **kw: ("ok", {}))],
                    audit_path=str(path))
    out = io.StringIO()
    stdio.serve(server, [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "t", "arguments": {}}})], out)
    assert json.loads(out.getvalue())["result"]["isError"] is False
    [line] = [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()]
    assert (line["transport"], line["client"]) == ("stdio", "stdio:%d" % os.getppid())


def test_tool_refuses_unknown_and_missing_arguments():
    tool = Tool("t", "d", tool_schema({
        "a": {"type": "string"}, "n": {"type": "integer"}, "x": {"type": "number"},
        "names": {"type": "array", "items": {"type": "string"}},
        "side": {"type": "string", "enum": ["attack", "defense"]}, "any": {},
        "expr": {"type": ["string", "number"]}}, ["a"]),
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
            ({"a": "x", "side": "sideways"}, "'side'", "must be one of 'attack', 'defense'"),
            ({"a": "x", "expr": True}, "'expr'", "must be string or number")):
        with pytest.raises(Refusal) as refused:
            tool(arguments)
        assert str(refused.value) == "t: %s %s" % (named, wanted)
    passing = {"a": "x", "n": 2, "x": 2, "names": ("Ana",), "side": "attack", "any": None}
    assert tool(passing) == ("ok", passing)
    for either in (2, "x"):                       # a list of types admits any of them
        assert tool({"a": "x", "expr": either}) == ("ok", {"a": "x", "expr": either})


def test_server_reports_a_refused_tool_as_is_error(tmp_path):
    """Every Refusal is the caller's error: the door answers it isError and
    audits it as refused - a TuneError as much as a Refusal raised plainly."""
    def refuse(**kw):
        raise Refusal("no")

    def refuse_a_tune(**kw):
        raise tune.TuneError("no strategy 'x'")
    empty = tool_schema()
    audit = tmp_path / "audit.jsonl"
    server = Server([Tool("t", "d", empty, refuse), Tool("tuned", "d", empty, refuse_a_tune)],
                    audit_path=str(audit))
    for name, said in (("t", "no"), ("tuned", "no strategy 'x'")):
        reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": name, "arguments": {}}}, "test")
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
    server = Server([Tool("t", "d", tool_schema(), crash)],
                    log=logged.append, audit_path=str(tmp_path / "audit.jsonl"))
    call = lambda method, params: server.handle(                      # noqa: E731
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, "test")
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


def test_a_request_of_the_wrong_shape_is_the_callers_error_and_logs_nothing(tmp_path):
    """A method that is not a string, params that are not an object, a tool
    name or a uri that is not a string: each is the request's error, never a
    fault with a traceback in the log. A notification still gets no reply."""
    logged = []
    server = Server([], tools.StrategyResources(), log=logged.append,
                    audit_path=str(tmp_path / "audit.jsonl"))

    def error(message):
        return server.handle(dict({"jsonrpc": "2.0", "id": 1}, **message), "test")["error"]
    assert error({"method": 5}) == {"code": -32600, "message": "method must be a string"}
    assert error({"method": "tools/call", "params": [1]}) == {
        "code": -32602, "message": "params must be an object"}
    assert error({"method": "tools/call", "params": {"name": ["t"]}}) == {
        "code": -32602, "message": "no tool named ['t']"}
    assert error({"method": "resources/read", "params": {"uri": 5}}) == {
        "code": -32602, "message": "uri must be a string"}
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized",
                          "params": [1]}, "test") is None
    assert logged == []


def test_the_strategy_resources_answer_an_unknown_uri_as_a_bad_parameter(tmp_path):
    """The one implementation of the resources a server serves: an id no file
    holds is a bad parameter, and a strategy's uri reads back its file."""
    server = Server([], tools.StrategyResources(), log=lambda message: None,
                    audit_path=str(tmp_path / "audit.jsonl"))

    def read(uri):
        return server.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/read",
                              "params": {"uri": uri}}, "test")
    missing = read("strategy://nope")["error"]
    assert missing == {"code": -32602, "message": "no resource at strategy://nope"}
    first = catalog.load()[0]
    assert read("strategy://" + first.id)["result"]["contents"][0]["text"] == first.raw


def test_a_key_error_while_reading_a_resource_is_the_servers_fault(tmp_path, monkeypatch):
    """Only NoSuchResourceError says the uri names nothing. A KeyError raised
    while a resource is read - inside the catalog, say - is INTERNAL, with
    its traceback in the log, as a fault inside a tool is."""
    def broken(directory=None):
        raise KeyError("inside the catalog")
    monkeypatch.setattr(catalog, "load", broken)
    logged = []
    server = Server([], tools.StrategyResources(), log=logged.append,
                    audit_path=str(tmp_path / "audit.jsonl"))
    fault = server.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/read",
                           "params": {"uri": "strategy://coverage"}}, "test")["error"]
    assert fault["code"] == -32603 and fault["message"].startswith("KeyError")
    assert logged and "Traceback" in logged[0]


def test_a_broken_playbook_is_a_server_fault_at_the_door(tmp_path, monkeypatch):
    """A playbook that does not load is the operator's to fix, not the caller's:
    every tool and resource that reads it answers INTERNAL with the catalog's
    own message, logs the traceback and is audited as crashed, in the same words."""
    empty = tmp_path / "playbook"
    empty.mkdir()
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(empty))
    logged = []
    audit = tmp_path / "audit.jsonl"
    server = Server(tools.REGISTRY.bind(tools.Context(dsn="postgresql://nowhere", client="test")),
                    tools.StrategyResources(), log=logged.append, audit_path=str(audit))
    for method, params in (("tools/call", {"name": "strategies", "arguments": {}}),
                           ("resources/list", {})):
        fault = server.handle({"jsonrpc": "2.0", "id": 1, "method": method,
                               "params": params}, "test")["error"]
        assert fault["code"] == -32603
        assert fault["message"].startswith("CatalogError: no strategies in")
    assert logged and all("Traceback" in entry for entry in logged)
    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["tool"] == "strategies"
    assert lines[0]["crashed"].startswith("CatalogError: no strategies in")


def test_an_audit_line_that_cannot_be_written_is_noted_on_stderr_and_not_raised(
        tmp_path, capsys):
    """The door stays open when its log fails, and says so where the operator
    looks - stderr, never stdout, which over stdio is the wire."""
    audit({"tool": "t"}, str(tmp_path))                 # a directory is no file to append to
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("countrix mcp: the audit log %s was not written: " % tmp_path)


def test_an_audit_line_records_sizes_and_type_names_never_values(tmp_path):
    """A string, a list or an object is recorded by its length; a number, a
    bool or None by its type name, so a tune's weight never reaches the log."""
    path = tmp_path / "audit.jsonl"
    arguments = {"weight": 7.25, "top": 3, "flag": True, "none": None, "names": ["Ana"],
                 "sql": "select 1"}
    assert audited("t", arguments, lambda: "ok", "in-process", "shell",
                   audit_path=str(path)) == "ok"
    [line] = [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()]
    assert line["args"] == {"weight": "float", "top": "int", "flag": "bool", "none": "NoneType",
                            "names": 1, "sql": 8}
    assert line["ok"] is True and line["client"] == "shell"


def test_the_suite_audits_to_a_temporary_file_never_the_repos_log():
    """conftest's audit_log points every call the suite makes away from
    db/raw/audit.jsonl, the log the sentry reads."""
    assert not os.path.abspath(default_audit_path()).startswith(
        os.path.abspath(RAW_DIR) + os.sep)
