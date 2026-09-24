"""orchestrator.py's verdict on the stack: the three health replies read into
lines, the data layer's state, a layer that answers with an error, and the
one board the readiness probe solves. The network is stubbed out."""

import json

import orchestrator


def test_verdict_reads_the_three_health_replies():
    ok, lines = orchestrator.verdict({
        "data": {"status": "ok", "state": "current", "table_count": 42, "heroes": 53,
                 "pending_migrations": [], "newest_capture": "2026-09-13"},
        "inference": {"status": "ok", "strategies": 38, "heroes": 53},
        "ui": {"heroes": [{}] * 53, "maps": [{}] * 30},
        "board": {"seconds": 1.0, "picks": []}})
    assert ok and lines == ["data layer: 42 tables, 53 heroes, rates captured 2026-09-13",
                            "inference: 38 strategies, 53 heroes, a board in 1.0s",
                            "board: 53 heroes on the roster, 30 maps"]
    ok, lines = orchestrator.verdict({
        "data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54,
                 "announced": 1, "pending_migrations": [], "newest_capture": "2026-09-14"},
        "inference": {"status": "ok", "strategies": 38, "heroes": 54},
        "ui": {"heroes": [{}] * 54, "maps": [{}] * 30},
        "board": {"seconds": 1.0, "picks": []}})
    assert ok and any("54 heroes (1 announced, not yet playable)" in line for line in lines)
    ok, lines = orchestrator.verdict({"data": {"status": "ok", "state": "stale",
                                               "table_count": 42, "heroes": 53,
                                               "pending_migrations": ["099_future.sql"]},
                                      "inference": {"status": "ok", "strategies": 0},
                                      "ui": None, "board": None})
    assert not ok
    assert [line.split(" (")[0] for line in lines] == [
        "data layer: schema behind the migrations", "data layer: 42 tables, 53 heroes,"
        " rates captured never", "inference: no strategies visible", "board: not answering"]
    assert "(099_future.sql)" in lines[0] and "stale bind mount" in lines[2]


def test_the_verdict_waits_on_the_data_layers_state():
    """Ready is the state the data layer reports, db.psql.schema.state; an
    image older than the checkout reports none, and is not ready either."""
    served = {
        "inference": {"status": "ok", "strategies": 38, "heroes": 54},
        "ui": {"heroes": [{}] * 54, "maps": [{}] * 30},
        "board": {"seconds": 1.0, "picks": []}}
    for state, said in (("empty", "no heroes yet"), ("unfilled", "no heroes yet"),
                        (None, "predates this checkout")):
        data = {"status": "ok", "table_count": 36, "heroes": 0, "pending_migrations": []}
        if state:
            data["state"] = state
        ok, lines = orchestrator.verdict(dict(served, data=data))
        assert not ok and any(said in line for line in lines), state


def test_health_urls_cover_every_served_layer():
    assert set(orchestrator.URLS) == {"data", "inference", "ui"}


def test_an_error_reply_reports_the_layers_own_message(monkeypatch):
    """A layer that answers with an error status is answering: get_json reads
    the body, and the verdict prints the layer's own words."""
    import io
    import urllib.error
    import urllib.request
    body = {}

    def failing(url, timeout=0):
        raise urllib.error.HTTPError(url, 500, "x", {}, io.BytesIO(body["raw"]))
    monkeypatch.setattr(urllib.request, "urlopen", failing)
    body["raw"] = json.dumps({"status": "degraded", "error": "no strategies in /x"}).encode()
    data = orchestrator.get_json("http://localhost:8020/health")
    assert data == {"status": "degraded", "error": "no strategies in /x"}
    body["raw"] = b"<html>a proxy's page</html>"
    assert orchestrator.get_json("http://localhost:8020/health") == {
        "status": "error", "error": "HTTP 500"}
    ok, lines = orchestrator.verdict({"data": data, "inference": None, "board": None,
                                      "ui": {"error": "TypeError: boom"}})
    assert not ok and "data layer: no strategies in /x" in lines
    assert "board: TypeError: boom" in lines


def test_readiness_solves_one_board_through_the_service(monkeypatch):
    """A six back from the probe means ready, anything else means not."""
    calls = []
    six = {"blue": {"blue": ["D.Va", "Winston", "Cassidy", "Genji", "Ana", "Brigitte"]}}
    monkeypatch.setattr(orchestrator, "get_json", lambda url, timeout=10: calls.append(url) or six)
    probe = orchestrator.probe()
    assert probe["picks"] == six["blue"]["blue"] and probe["seconds"] >= 0
    assert calls == [orchestrator.PROBE]
    monkeypatch.setattr(orchestrator, "get_json", lambda url, timeout=10: {"error": "died"})
    assert orchestrator.probe() is None
    inf = {"status": "ok", "strategies": 300, "heroes": 54}
    served = {
        "data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54},
        "inference": inf, "ui": {"heroes": [{}] * 54, "maps": [{}] * 30}}
    ok, lines = orchestrator.verdict(dict(served, board={"seconds": 2.4, "picks": six}))
    assert ok and any(line.endswith("a board in 2.4s") for line in lines)
    ok, lines = orchestrator.verdict(dict(served, board=None))
    assert not ok and any("a board did not solve" in line for line in lines)
