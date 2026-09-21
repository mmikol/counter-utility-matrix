"""The board over HTTP: the same handlers the unit tests call, served."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from ui import board


@pytest.fixture()
def served():
    server = ThreadingHTTPServer(("127.0.0.1", 0), board.Handler)
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


def test_a_read_only_board_refuses_the_one_post(served, monkeypatch):
    # the default: a weight set on the page is the session's own and reaches no file.
    # the sentinel records rather than raising: pytest.fail raises BaseException,
    # which do_POST's `except Exception` misses, killing the handler thread instead
    wrote = []
    monkeypatch.setattr(board, "READ_ONLY", True)
    monkeypatch.setattr(board, "api_weight", lambda payload: (wrote.append(payload), ({}, 200))[1])
    code, data = post(served + "/api/weight", {"id": "coverage", "weight": 3})
    assert code == 403 and "session only" in data["error"]
    assert wrote == [], wrote
    assert "READ_ONLY = true" in board.view_board()


def test_a_writable_board_renders_the_store_button(monkeypatch):
    # COUNTRIX_READ_ONLY=0 is the documented escape hatch: the page shell
    # must hand the scripts READ_ONLY = false, which is what renders *store*
    monkeypatch.setattr(board, "READ_ONLY", False)
    assert "READ_ONLY = false" in board.view_board()


def test_the_weight_store_is_the_only_post_and_reads_a_small_json_body(served, monkeypatch):
    monkeypatch.setattr(board, "READ_ONLY", False)
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


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()


def test_the_page_the_statics_the_math_and_the_strategies_need_no_database(served, monkeypatch):
    monkeypatch.setattr(board, "dsn", lambda: "postgresql://nobody@127.0.0.1:9/nowhere")
    code, ctype, body = get(served + "/")
    assert code == 200 and "text/html" in ctype and b"Countrix" in body
    code, ctype, body = get(served + "/tests")
    assert code == 200 and "text/html" in ctype
    assert b"What is claimed" in body and b"What is not proven" in body
    code, ctype, body = get(served + "/static/board.css")
    assert code == 200 and "text/css" in ctype and b".tile" in body
    assert get(served + "/static/nope.txt")[0] == 404
    code, _, body = get(served + "/math")
    assert code == 200 and b"The Counter Utility Matrix" in body
    code, _, body = get(served + "/api/strategies")
    assert code == 200 and json.loads(body)["strategies"]
    assert get(served + "/nothing")[0] == 404
    # the database is not there. A JSON route answers JSON, as the sibling service does
    code, ctype, body = get(served + "/api/roster")
    assert code == 500 and "application/json" in ctype and json.loads(body)["error"]
    code, ctype, body = get(served + "/api/nothing")
    assert code == 404 and "application/json" in ctype and json.loads(body)["error"]


@pytest.mark.invariant
def test_the_json_endpoints_answer_over_http(served, monkeypatch, dsn):
    monkeypatch.setattr(board, "dsn", lambda: dsn)
    code, _, body = get(served + "/api/roster")
    assert code == 200 and len(json.loads(body)["heroes"]) > 50
    code, _, body = get(served + "/api/facts?map=Ilios&blue=Ana")
    assert code == 200 and json.loads(body)["count"] > 0
    code, _, body = get(served + "/api/infer?map=Ilios&blue=Ana&bans=Widowmaker")
    assert code == 200 and json.loads(body)["blue"]["blue"] and json.loads(body)["plan"]
    code, _, body = get(served + "/api/infer?blue=Nobody")
    assert code == 400 and "error" in json.loads(body)
