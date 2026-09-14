"""The inference engine as a service: its handlers speak the same results
the engine returns in-process, and the board forwards to it when told to."""

from urllib.parse import quote

import pytest

from inference import catalog, serve
from ui import board

pytestmark = pytest.mark.invariant


def test_service_infers_evaluates_and_lists(db):
    data, code = serve.handle_infer(db, {"map": ["King's Row"], "red": ["Zarya"],
                                         "blue": ["Ana"]})
    assert code == 200 and data["kind"] == "infer" and len(data["blue"]) == 6
    data, code = serve.handle_infer(db, {"blue": ["Reinhardt", "Zarya", "Widowmaker",
                                                  "Bastion", "Ana", "Lúcio"]})
    assert code == 200 and data["kind"] == "evaluate"
    data, code = serve.handle_evaluate(db, {"blue": ["Ana"]})
    assert code == 400 and "exactly 6" in data["error"]
    data, code = serve.handle_heuristics()
    assert code == 200 and len(data["strategies"]) == len(catalog.load())
    data, code = serve.handle_board(db, {"map": ["King's Row"], "red": ["Zarya"],
                                         "blue": ["Ana"], "side": ["defense"]})
    assert code == 200 and data["red"]["side"] == "attack" and data["current"]["partial"]
    assert not hasattr(serve, "handle_record")          # recording is gone
    db.rollback()


def test_health_reports_the_catalog_and_the_database():
    data, code = serve.handle_health()
    assert code == 200 and data["strategies"] == len(catalog.load())
    assert data["status"] in ("ok", "degraded")


def test_board_forwards_to_a_named_inference_service(monkeypatch):
    calls = []

    def fake_remote(path, query=None, payload=None):
        calls.append((path, query, payload))
        return {"forwarded": True}, 200

    monkeypatch.setattr(board, "INFERENCE_URL", "http://inference:8019")
    monkeypatch.setattr(board, "remote", fake_remote)
    assert board.api_infer(None, {"map": ["Ilios"], "red": ["Zarya"], "blue": []}) == (
        {"forwarded": True}, 200)
    assert calls[-1] == ("/board", {"map": "Ilios", "side": "", "red": ["Zarya"],
                                    "blue": [], "ban": []}, None)
    board.api_infer(None, {"map": ["Ilios"], "weight": ["healing-floor:9.99", "x:12", "junk"]})
    assert calls[-1][1]["weight"] == ["healing-floor:9.99", "x:10"]   # clamped, junk dropped
    assert board.api_strategies() == {"forwarded": True}


def test_board_reports_an_unreachable_inference_service(monkeypatch):
    monkeypatch.setattr(board, "INFERENCE_URL", "http://127.0.0.1:9")
    data, code = board.remote("/health")
    assert code == 502 and "unreachable" in data["error"]


# --- served ------------------------------------------------------------------------------

@pytest.fixture()
def served():
    import threading
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


def _get(url):
    import json
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_health_and_strategies_are_served_without_a_database(served, monkeypatch):
    monkeypatch.setattr(serve.psql, "default_dsn", lambda: "postgresql://nobody@127.0.0.1:9/nowhere")
    code, data = _get(served + "/health")
    assert code == 200 and data["strategies"] == len(catalog.load())
    code, data = _get(served + "/strategies")
    assert code == 200 and len(data["strategies"]) == len(catalog.load())
    assert _get(served + "/nothing")[0] == 404
    code, data = _get(served + "/board?map=Ilios")           # no database: the error, as JSON
    assert code == 500 and "error" in data


@pytest.mark.invariant
def test_board_infer_and_evaluate_are_served(served, monkeypatch, dsn):
    monkeypatch.setattr(serve.psql, "default_dsn", lambda: dsn)
    code, data = _get(served + "/board?map=Ilios&blue=Ana&red=Zarya")
    assert code == 200 and data["blue"]["blue"] and data["momentum"]["verdict"]
    code, data = _get(served + "/infer?map=Ilios&red=Zarya")
    assert code == 200 and len(data["blue"]) == 6
    six = "&".join("blue=" + quote(h) for h in data["blue"])
    code, data = _get(served + "/evaluate?map=Ilios&red=Zarya&" + six)
    assert code == 200 and data["rank"] == 1
    code, data = _get(served + "/evaluate?map=Ilios&blue=Ana")
    assert code == 400 and "error" in data
