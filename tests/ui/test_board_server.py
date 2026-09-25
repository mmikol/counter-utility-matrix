"""The board over HTTP: the same handlers the unit tests call, served."""

import http.client
import json
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import urlparse

import pytest

from db import Refusal, web
from ui import board, pages

NOWHERE = "postgresql://nobody@127.0.0.1:9/nowhere"


@pytest.fixture()
def served():
    server = web.LocalServer(("127.0.0.1", 0), board.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


def post(url, body, headers=None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()


def test_a_read_only_board_refuses_the_one_post(served, monkeypatch):
    # the default: a weight set on the page is the session's own and reaches no file.
    # the sentinel records rather than raising: pytest.fail raises BaseException,
    # which do_POST's `except Exception` misses, killing the handler thread instead
    wrote = []
    monkeypatch.setenv("COUNTRIX_READ_ONLY", "1")
    monkeypatch.setattr(board, "api_weight", lambda payload: (wrote.append(payload), ({}, 200))[1])
    code, data = post(served + "/api/weight", {"id": "coverage", "weight": 3})
    assert code == 403 and "session only" in data["error"]
    assert wrote == [], wrote
    assert "READ_ONLY = true" in pages.view_board(board.read_only())


def test_a_writable_board_renders_the_store_button(monkeypatch):
    # COUNTRIX_READ_ONLY=0 is the documented escape hatch: the page shell
    # must hand the scripts READ_ONLY = false, which is what renders *store*
    monkeypatch.setenv("COUNTRIX_READ_ONLY", "0")
    assert "READ_ONLY = false" in pages.view_board(board.read_only())


def test_the_board_listens_where_the_environment_says(monkeypatch):
    # the host and the port are read together, when the board starts
    monkeypatch.setenv("COUNTRIX_UI_HOST", "0.0.0.0")
    monkeypatch.setenv("COUNTRIX_UI_PORT", "8018")
    args = board.command_line([])
    assert (args.host, args.port) == ("0.0.0.0", 8018)
    monkeypatch.delenv("COUNTRIX_UI_HOST")
    monkeypatch.delenv("COUNTRIX_UI_PORT")
    args = board.command_line([])
    assert (args.host, args.port) == ("127.0.0.1", 8017)
    assert board.command_line(["--port", "9"]).port == 9      # a flag still wins
    # the names it answers to beyond the local ones: none unless given
    assert args.allow_host == []
    assert board.command_line(["--allow-host", "x", "--allow-host", "y"]).allow_host == ["x", "y"]


def test_the_weight_store_is_the_only_post_and_reads_a_small_json_body(served, monkeypatch):
    monkeypatch.setenv("COUNTRIX_READ_ONLY", "0")
    monkeypatch.setattr(board, "api_weight",
                        lambda payload: ({"line": "tuned %s" % payload["id"]}, 200))
    code, data = post(served + "/api/weight", {"id": "coverage", "weight": 3})
    assert code == 200 and data == {"line": "tuned coverage"}
    assert post(served + "/api/weight", b"{not json")[0] == 400
    assert post(served + "/api/weight", b"")[0] == 400
    assert post(served + "/api/weight", b"x" * 5000)[0] == 400
    assert post(served + "/api/facts", {"id": "coverage"})[0] == 404
    # the door's guards, on the board's one write too: a browser sends Origin, and
    # only a local one passes; a body that does not claim JSON is refused unread
    body = {"id": "coverage", "weight": 3}
    assert post(served + "/api/weight", body, {"Origin": "http://evil.example"})[0] == 403
    assert post(served + "/api/weight", body, {"Origin": "http://localhost:8017"})[0] == 200
    assert post(served + "/api/weight", b"{}", {"Content-Type": "text/plain"})[0] == 415


def test_a_foreign_host_or_origin_is_refused_on_every_route(served, monkeypatch):
    """The guard runs before any route: a page rebound to the board's address
    sends its GETs under its own host name and no Origin, and a cross-site
    request carries a foreign Origin - both are 403, reads included."""
    monkeypatch.setattr(board.psql, "default_dsn", lambda: NOWHERE)
    for path in ("/", "/api/strategies"):
        assert get(served + path, {"Host": "evil.example"})[0] == 403, path
        assert get(served + path, {"Origin": "http://evil.example"})[0] == 403, path
        assert get(served + path, {"Host": "localhost:8017"})[0] == 200, path


def test_the_one_post_says_what_went_wrong_and_bad_json_means_only_that(served, monkeypatch):
    """The header, the body and the store fail apart: a Content-Length that is
    not a number is named, and what the store raises is its own answer - a
    refusal 400 with its reason, anything else 500 - never "bad JSON"."""
    monkeypatch.setenv("COUNTRIX_READ_ONLY", "0")
    address = urlparse(served)
    connection = http.client.HTTPConnection(address.hostname, address.port, timeout=60)
    connection.request("POST", "/api/weight", body=b"{}", headers={
        "Content-Type": "application/json", "Content-Length": "abc"})
    response = connection.getresponse()
    assert response.status == 400 and "Content-Length" in json.loads(response.read())["error"]
    connection.close()
    body = {"id": "coverage", "weight": 3}

    def refused(payload):
        raise Refusal("no strategy 'coverage'")
    monkeypatch.setattr(board, "api_weight", refused)
    assert post(served + "/api/weight", body) == (400, {"error": "no strategy 'coverage'"})

    def broken(payload):
        raise ValueError("inside")
    monkeypatch.setattr(board, "api_weight", broken)
    code, data = post(served + "/api/weight", body)
    assert code == 500 and data["error"] == "ValueError: inside"


def test_the_page_the_statics_the_math_and_the_strategies_need_no_database(
        served, monkeypatch, tmp_path):
    monkeypatch.setattr(board.psql, "default_dsn", lambda: NOWHERE)
    code, ctype, body = get(served + "/")
    assert code == 200 and "text/html" in ctype and b"Countrix" in body
    code, ctype, body = get(served + "/tests")
    assert code == 200 and "text/html" in ctype
    assert b"What is claimed" in body and b"What is not proven" in body
    code, ctype, body = get(served + "/static/board.css")
    assert code == 200 and "text/css" in ctype and b".tile" in body
    code, ctype, body = get(served + "/static/bebas-neue.woff2")
    assert code == 200 and ctype == "font/woff2" and body.startswith(b"wOF2")
    assert get(served + "/static/nope.txt")[0] == 404
    assert get(served + "/static/OFL.txt")[0] == 404        # the licence ships, unserved
    code, _, body = get(served + "/math")
    assert code == 200 and b"The Counter Utility Matrix" in body
    code, _, body = get(served + "/api/strategies")
    assert code == 200 and json.loads(body)["strategies"]
    with monkeypatch.context() as broken:                 # a playbook that does not load
        broken.setenv("COUNTRIX_STRATEGIES", str(tmp_path))
        code, _, body = get(served + "/api/strategies")
    assert code == 500 and json.loads(body)["error"].startswith("CatalogError: no strategies in")
    assert get(served + "/nothing")[0] == 404
    # the database is not there. A JSON route answers JSON, as the sibling service does
    code, ctype, body = get(served + "/api/roster")
    error = json.loads(body)["error"]
    assert code == 500 and "application/json" in ctype and error
    assert "Traceback" not in error                       # the stack goes to stderr only
    code, ctype, body = get(served + "/api/nothing")
    assert code == 404 and "application/json" in ctype and json.loads(body)["error"]


def test_a_board_on_the_service_answers_while_the_database_is_down(served, monkeypatch):
    """With the inference service named, a board request is forwarded before
    any connection opens, so it answers with the database out of reach - a
    500 when the router connected first."""
    monkeypatch.setenv("COUNTRIX_INFERENCE_URL", "http://inference:8019")
    monkeypatch.setattr(board.psql, "default_dsn", lambda: NOWHERE)
    monkeypatch.setattr(board, "remote", lambda path, query=None, payload=None: (
        {"forwarded": path, "client": query.get("client")}, 200))
    code, _, body = get(served + "/api/board?map=Ilios&blue=Ana&client=tab1")
    assert code == 200 and json.loads(body) == {"forwarded": "/board", "client": ["tab1"]}


def test_a_board_leaves_a_line_on_stderr_and_a_static_file_none(served, monkeypatch, capsys):
    """The solves are logged with their status and seconds, so the container's
    log says what the page asked and when; the page and its files are quiet
    unless they fail."""
    monkeypatch.setenv("COUNTRIX_INFERENCE_URL", "http://inference:8019")
    monkeypatch.setattr(board, "remote", lambda path, query=None, payload=None: ({}, 200))
    capsys.readouterr()
    assert get(served + "/static/board.css")[0] == 200 and get(served + "/")[0] == 200
    assert capsys.readouterr().err == ""
    assert get(served + "/api/board?map=Ilios")[0] == 200
    assert re.search(r'"GET /api/board\?map=Ilios HTTP/1.1" 200 \d+\.\d\ds$',
                     capsys.readouterr().err.rstrip())
    assert get(served + "/static/nope.js")[0] == 404
    assert '"GET /static/nope.js HTTP/1.1" 404' in capsys.readouterr().err


@pytest.mark.invariant
def test_the_json_endpoints_answer_over_http(served, monkeypatch, dsn):
    monkeypatch.setattr(board.psql, "default_dsn", lambda: dsn)
    code, _, body = get(served + "/api/roster")
    assert code == 200 and len(json.loads(body)["heroes"]) > 50
    code, _, body = get(served + "/api/facts?map=Ilios&blue=Ana")
    assert code == 200 and json.loads(body)["count"] > 0
    code, _, body = get(served + "/api/board?map=Ilios&blue=Ana&bans=Widowmaker")
    assert code == 200 and json.loads(body)["blue"]["blue"] and json.loads(body)["plan"]
    code, _, body = get(served + "/api/board?blue=Nobody")
    assert code == 400 and "error" in json.loads(body)
