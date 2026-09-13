"""The inference engine as a service: its handlers speak the same results
the engine returns in-process, and the board forwards to it when told to."""

import pytest

from user import board
from inference import serve

pytestmark = pytest.mark.invariant


def test_service_infers_evaluates_and_lists(db):
    data, code = serve.handle_infer(db, {"map": ["King's Row"], "red": ["Zarya"],
                                         "blue": ["Ana"]})
    assert code == 200 and data["kind"] == "infer" and len(data["blue"]) == 5
    data, code = serve.handle_infer(db, {"blue": ["Reinhardt", "Widowmaker", "Bastion",
                                                  "Ana", "Lúcio"]})
    assert code == 200 and data["kind"] == "evaluate"
    data, code = serve.handle_evaluate(db, {"blue": ["Ana"]})
    assert code == 400 and "five" in data["error"]
    data, code = serve.handle_heuristics()
    assert code == 200 and len(data["heuristics"]) >= 30
    data, code = serve.handle_record(db, {"answer": {"picks": []}})
    assert code == 400
    db.rollback()


def test_health_reports_the_catalog_and_the_database():
    data, code = serve.handle_health()
    assert code == 200 and data["heuristics"] >= 30 and data["status"] in ("ok", "degraded")


def test_board_forwards_to_a_named_inference_service(monkeypatch):
    calls = []

    def fake_remote(path, query=None, payload=None):
        calls.append((path, query, payload))
        return {"forwarded": True}, 200

    monkeypatch.setattr(board, "INFERENCE_URL", "http://inference:8019")
    monkeypatch.setattr(board, "remote", fake_remote)
    assert board.api_infer(None, {"map": ["Ilios"], "red": ["Zarya"], "blue": []}) == (
        {"forwarded": True}, 200)
    assert calls[-1] == ("/infer", {"map": "Ilios", "red": ["Zarya"], "blue": []}, None)
    assert board.api_heuristics() == {"forwarded": True}
    assert board.api_record(None, {"answer": {}}) == ({"forwarded": True}, 200)
    assert calls[-1][0] == "/record"


def test_board_reports_an_unreachable_inference_service(monkeypatch):
    monkeypatch.setattr(board, "INFERENCE_URL", "http://127.0.0.1:9")
    data, code = board.remote("/health")
    assert code == 502 and "unreachable" in data["error"]
