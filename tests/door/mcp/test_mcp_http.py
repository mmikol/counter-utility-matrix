"""The door over Streamable HTTP, the data-layer container's: the real
server spawned on a free port, and an in-process HttpServer for the guards -
the origin check, the bearer token, the body and batch caps, the rate limit
per client address and the audit line each call leaves."""

import http.client
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import pytest

from db import ROOT
from door.mcp import tools
from door.mcp.http import HttpServer
from door.mcp.server import Server


@pytest.fixture(scope="module")
def http_server(tmp_path_factory):
    """The server over HTTP on a free port, once it answers /health. A child
    that exits first, or never answers, fails the fixture with its own
    stderr, which goes to a file: a pipe nobody reads fills and blocks it."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    base = "http://127.0.0.1:%d" % port
    log = tmp_path_factory.mktemp("mcp_http") / "stderr.log"
    with log.open("wb") as err:
        proc = subprocess.Popen(
            [sys.executable, "-m", "door.mcp", "--http", "127.0.0.1:%d" % port],
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


def _http_server(tmp_path, token=None, rate_limit=120):

    mcp = Server(tools.REGISTRY.bind(tools.Context(dsn="postgresql://nowhere")), None,
                 audit_path=str(tmp_path / "audit.jsonl"))
    httpd = HttpServer(("127.0.0.1", 0), mcp, lambda: {"status": "ok"}, token=token,
                       rate_limit=rate_limit)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


def _knock(url, body, headers=None):
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
