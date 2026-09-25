"""What the three HTTP servers share: the reply to a request that raised, the
Host-and-Origin guard, the handler base that logs what failed, the one JSON
reader and the one client that calls the MCP door."""

import email.message
import http.client
import io
import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from db import Refusal, web
from door.mcp.http import HttpServer
from door.mcp.schema import Tool, tool_schema
from door.mcp.server import Server


def test_a_refusal_is_400_and_anything_else_500_without_a_traceback(capsys):
    assert web.failure(Refusal("x")) == ({"error": "x"}, 400)
    assert capsys.readouterr().err == ""
    # raised, not built: an error never raised carries no traceback to print
    try:
        raise KeyError("k")
    except KeyError as error:
        reply = web.failure(error)
    assert reply == ({"error": "KeyError: 'k'"}, 500)
    assert "Traceback" in capsys.readouterr().err


def _headers(**fields):
    message = email.message.Message()
    for name, value in fields.items():
        message[name] = value
    return message


def test_a_request_must_name_the_server_by_its_host_and_its_origin():
    allowed = web.LOCAL_HOSTS | {"inference"}
    for host in ("localhost:8017", "127.0.0.1", "[::1]:8020", "LOCALHOST", "inference:8019"):
        assert web.request_allowed(_headers(Host=host), allowed), host
    # a rebound page sends no Origin on a same-origin GET, but its own host name
    for host in ("evil.example", "evil.example:8017", "localhost.evil.example", "[::1", ""):
        assert not web.request_allowed(_headers(Host=host), allowed), host
    assert not web.request_allowed(_headers(), allowed)                      # no Host at all
    assert web.request_allowed(_headers(Host="localhost", Origin="http://localhost:8017"), allowed)
    for origin in ("http://evil.example", "null", ""):
        assert not web.request_allowed(_headers(Host="localhost", Origin=origin), allowed), origin


@pytest.fixture()
def served():
    """A web.Handler with one route, served on a free port."""
    class Hello(web.Handler):
        timed = frozenset({"/slow"})

        def do_GET(self):
            self._json({"hello": "world"}, 404 if self.path == "/missing" else 200)

    server = web.LocalServer(("127.0.0.1", 0), Hello)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def _get(port, path, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request("GET", path, headers=headers or {})
    response = connection.getresponse()
    status, body = response.status, response.read()
    connection.close()
    return status, json.loads(body)


def test_the_handler_logs_what_failed_and_the_timed_routes_alone(served, capsys):
    # log_request runs inside send_response, before the client reads the reply
    assert _get(served, "/") == (200, {"hello": "world"})
    assert capsys.readouterr().err == ""
    assert _get(served, "/", {"Host": "evil.example"}) == (
        403, {"error": "host or origin not allowed"})
    assert '"GET / HTTP/1.1" 403' in capsys.readouterr().err
    assert _get(served, "/missing")[0] == 404
    assert '"GET /missing HTTP/1.1" 404' in capsys.readouterr().err
    assert _get(served, "/slow?x=1")[0] == 200                 # a timed route: its seconds too
    assert re.search(r'"GET /slow\?x=1 HTTP/1.1" 200 \d+\.\d\ds$', capsys.readouterr().err.rstrip())


# --- the client ------------------------------------------------------------------------

def _door(tmp_path, token=None):
    """A real MCP door over HTTP on a free port, serving two tools."""
    def hello(**kw):
        return "hello\nsecond line", {"said": "hello"}

    def refuse(**kw):
        raise Refusal("no strategy 'x'")
    empty = tool_schema()
    mcp = Server([Tool("hello", "d", empty, hello), Tool("refuse", "d", empty, refuse)],
                 audit_path=str(tmp_path / "audit.jsonl"))
    httpd = HttpServer(("127.0.0.1", 0), mcp, lambda: {"status": "ok"}, token=token)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d/mcp" % httpd.server_address[1]


class _Answered(io.BytesIO):
    """What a stubbed urlopen answers: a body and a status."""

    def __init__(self, body, status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_read_json_reads_the_status_and_body_of_any_answer(tmp_path, monkeypatch):
    httpd, url = _door(tmp_path, token="s3cret")
    health = url.replace("/mcp", "/health")                  # open without the token
    assert web.read_json(health, 10) == web.JsonAnswer(200, {"status": "ok"})
    ping = urllib.request.Request(
        url, data=b'{"jsonrpc": "2.0", "id": 1, "method": "ping"}',
        headers={"Content-Type": "application/json"})
    assert web.read_json(ping, 10) == web.JsonAnswer(401, {"error": "a bearer token is required"})
    httpd.shutdown()
    with pytest.raises(OSError):                             # nothing answers: the caller's to word
        web.read_json("http://127.0.0.1:9/mcp", 5)
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: _Answered(b"<html>"))
    assert web.read_json(health, 10) == web.JsonAnswer(200, None)


def test_call_tool_reads_the_answer_the_refusal_and_the_door_turning_it_away(tmp_path):
    httpd, url = _door(tmp_path)
    assert web.call_tool(url, "hello", {}) == web.CallReply(
        "hello\nsecond line", {"said": "hello"}, 200)
    assert web.call_tool(url, "refuse", {}) == web.CallReply("no strategy 'x'", None, 400)
    httpd.shutdown()
    httpd, url = _door(tmp_path, token="s3cret")
    # the token the door refused is the relay's own, not its caller's: 502
    assert web.call_tool(url, "hello", {}) == web.CallReply(
        "the MCP server answered 401: a bearer token is required", None, 502)
    assert web.call_tool(url, "hello", {}, token="s3cret").text == "hello\nsecond line"
    httpd.shutdown()
    nobody = web.call_tool("http://127.0.0.1:9/mcp", "hello", {}, timeout=5)
    assert nobody.status == 502 and nobody.is_error and "unreachable" in nobody.text
    with pytest.raises(ValueError, match="http or https"):
        web.call_tool("file:///etc/passwd", "hello", {})


def test_the_doors_rate_limit_passes_through_and_its_other_refusals_are_502(monkeypatch):
    """The door's 429 is relayed as it came; a body too large (413), and a
    200 that is not JSON-RPC, are the door failing the call: 502."""
    def refusing(code, reason):
        def urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, code, "x", email.message.Message(),
                                         io.BytesIO(json.dumps({"error": reason}).encode()))
        return urlopen
    for code, reason in ((429, "too many calls; try again in a minute"),
                         (413, "request too large")):
        monkeypatch.setattr(urllib.request, "urlopen", refusing(code, reason))
        assert web.call_tool("http://door/mcp", "hello", {}) == web.CallReply(
            "the MCP server answered %d: %s" % (code, reason), None, 429 if code == 429 else 502)
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: _Answered(b"<html>"))
    assert web.call_tool("http://door/mcp", "hello", {}) == web.CallReply(
        "the MCP server answered with no JSON-RPC response", None, 502)


def test_a_tools_call_response_is_read_field_by_field():
    """The client reads each field of the door's answer for its type: a
    response with no result says nothing and is no error, content that is not
    a list and a payload that is not an object read as none, and content
    items that are not text are left out. The tool's refusal is 400; a
    JSON-RPC error, or no response, is the door failing: 502."""
    nothing = web.CallReply("", None, 200)
    assert web._answer({"jsonrpc": "2.0", "id": 1}) == nothing
    assert web._answer({"jsonrpc": "2.0", "id": 1, "result": [1]}) == nothing
    assert web._answer({"result": {"content": 5, "structuredContent": [1]}}) == nothing
    items = [{"type": "image"}, {"type": "text", "text": "a"}, "b", {"type": "text", "text": "c"}]
    assert web._answer({"result": {"content": items, "isError": True}}) == web.CallReply(
        "a\nc", None, 400)
    assert web._answer({"error": {"code": -32602, "message": "no tool named 'x'"}}) == (
        web.CallReply("no tool named 'x'", None, 502))
    assert web._answer([]) == web.CallReply(
        "the MCP server answered with no JSON-RPC response", None, 502)
    assert not nothing.is_error and web._answer([]).is_error
