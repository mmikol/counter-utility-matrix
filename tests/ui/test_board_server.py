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


def post(url, body):
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_the_weight_store_is_the_only_post_and_reads_a_small_json_body(served, monkeypatch):
    monkeypatch.setattr(board, "api_weight",
                        lambda payload: ({"line": "tuned %s" % payload["id"]}, 200))
    code, data = post(served + "/api/weight", {"id": "coverage", "weight": 3})
    assert code == 200 and data == {"line": "tuned coverage"}
    assert post(served + "/api/weight", b"{not json")[0] == 400
    assert post(served + "/api/weight", b"")[0] == 400
    assert post(served + "/api/weight", b"x" * 5000)[0] == 400
    assert post(served + "/api/facts", {"id": "coverage"})[0] == 404


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()


def test_the_page_the_statics_the_math_and_the_strategies_need_no_database(served, monkeypatch):
    monkeypatch.setattr(board, "dsn", lambda: "postgresql://nobody@127.0.0.1:9/nowhere")
    code, ctype, body = get(served + "/")
    assert code == 200 and "text/html" in ctype and b"Counter" in body
    code, ctype, body = get(served + "/static/board.css")
    assert code == 200 and "text/css" in ctype and b".tile" in body
    assert get(served + "/static/nope.txt")[0] == 404
    code, _, body = get(served + "/math")
    assert code == 200 and b"The equation" in body
    code, _, body = get(served + "/api/strategies")
    assert code == 200 and json.loads(body)["strategies"]
    assert get(served + "/nothing")[0] == 404
    code, _, body = get(served + "/api/roster")         # the database is not there: an error page
    assert code == 500 and b"error" in body


@pytest.mark.invariant
def test_the_json_endpoints_answer_over_http(served, monkeypatch, dsn):
    monkeypatch.setattr(board, "dsn", lambda: dsn)
    code, _, body = get(served + "/api/roster")
    assert code == 200 and len(json.loads(body)["heroes"]) > 50
    code, _, body = get(served + "/api/facts?map=Ilios&blue=Ana")
    assert code == 200 and json.loads(body)["count"] > 0
    code, _, body = get(served + "/api/infer?map=Ilios&blue=Ana&ban=Widowmaker")
    assert code == 200 and json.loads(body)["blue"]["blue"] and json.loads(body)["plan"]
    code, _, body = get(served + "/api/infer?blue=Nobody")
    assert code == 400 and "error" in json.loads(body)
