"""The inference engine as a service: its handlers speak the same results
the engine returns in-process, and the board forwards to it when told to."""

from urllib.parse import quote

import pytest

from db import Refusal
from inference import catalog, serve
from ui import board


def test_the_board_survives_the_round_trip_through_a_query_string():
    """One owner for the wire: what board_query writes, parse_board reads back,
    so the two doors cannot drift apart on a spelling."""
    from urllib.parse import parse_qs, urlencode

    from ui.facts.draft import Draft, board_query, parse_board
    for draft in (Draft("King's Row", ("Zarya", "Pharah"), ("Ana",), ("Widowmaker",), "attack"),
                  Draft()):
        written = urlencode(board_query(draft), doseq=True)
        assert parse_board(parse_qs(written)) == draft


def test_both_doors_bound_the_search_with_one_clamp():
    """A caller naming pool or top reaches the same bounds through the service
    as through the MCP tools: the engine owns the definition."""
    from inference.engine import clamp_search
    assert clamp_search(None, None) == (6, 5)                  # the defaults
    assert clamp_search(0, 0) == (6, 5)                        # falsy reads as unset
    assert clamp_search(1, 0.5) == (2, 1)
    assert clamp_search(99, 99) == (12, 20)
    assert clamp_search("8", "3") == (8, 3)                    # a query string is text
    for junk in ("x", [1], object()):                          # a refusal, not a crash
        with pytest.raises(Refusal, match="must be numbers"):
            clamp_search(junk)
    assert clamp_search([], []) == (6, 5)                      # empty is unset, like None


@pytest.mark.invariant
def test_service_infers_evaluates_and_lists(db):
    data, code = serve.handle_infer(db, {"map": ["King's Row"], "red": ["Zarya"],
                                         "blue": ["Ana"]})
    assert code == 200 and data["kind"] == "infer" and len(data["blue"]) == 6
    six = ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"]
    data, code = serve.handle_infer(db, {"blue": six})
    # /infer infers whatever blue holds; ranking a full six against the field is
    # /evaluate's question, and the MCP tool of the same name draws the line here too
    assert code == 200 and data["kind"] == "infer" and sorted(data["blue"]) == sorted(six)
    with pytest.raises(Refusal, match="exactly 6"):     # the boundary answers it 400
        serve.handle_evaluate(db, {"blue": ["Ana"]})
    data, code = serve.handle_strategies()
    assert code == 200 and len(data["strategies"]) == len(catalog.load())
    data, code = serve.handle_board(db, {"map": ["King's Row"], "red": ["Zarya"],
                                         "blue": ["Ana"], "side": ["defense"]})
    assert code == 200 and data["red"]["side"] == "attack" and data["current"]["partial"]
    db.rollback()


@pytest.mark.invariant                    # default_dsn() touches the embedded cluster
def test_health_reports_the_catalog_and_the_database():
    data, code = serve.handle_health()
    assert code == 200 and data["strategies"] == len(catalog.load())
    assert data["status"] in ("ok", "degraded")


def test_a_host_without_pgserver_is_told_to_set_database_url(monkeypatch):
    """The image and CI carry no pgserver. With no DATABASE_URL either there is
    no database, and the one useful answer names the variable to set: an
    ImportError, which /health reports as degraded."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(serve.psql, "pgserver", None)
    with pytest.raises(ImportError, match="DATABASE_URL"):
        serve.psql.default_dsn()
    data, code = serve.handle_health()
    assert code == 200 and data["status"] == "degraded" and "DATABASE_URL" in data["error"]


def test_a_pid_file_race_degrades_health(monkeypatch):
    """default_dsn's second look at pgserver's pid file can meet it emptied
    again by another process: a JSONDecodeError, one of the ways the database
    is out of reach, so /health answers 200 and degraded."""
    import json

    def raced():
        raise json.JSONDecodeError("Expecting value", "", 0)
    monkeypatch.setattr(serve.psql, "default_dsn", raced)
    data, code = serve.handle_health()
    assert code == 200 and data["status"] == "degraded" and "Expecting value" in data["error"]


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
                                    "blue": [], "bans": []}, None)
    board.api_infer(None, {"map": ["Ilios"], "weights": ["healing-floor:9.99", "x:12"]})
    assert calls[-1][1]["weights"] == ["healing-floor:9.99", "x:10"]  # clamped
    # a malformed weight is the caller's error, refused here and never forwarded
    forwarded = len(calls)
    with pytest.raises(Refusal, match="id:value"):
        board.api_infer(None, {"map": ["Ilios"], "weights": ["junk"]})
    assert len(calls) == forwarded
    # the status rides along now: a 502 from the service is not served as a 200
    assert board.api_strategies() == ({"forwarded": True}, 200)


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
    assert code == 500 and data["error"] and "Traceback" not in data["error"]


def test_a_broken_playbook_degrades_health_and_fails_the_strategies_route(
        served, monkeypatch, tmp_path):
    """A playbook that does not load is the server's fault: /health stays 200
    and says degraded with the catalog's own words, so orchestrator.py prints
    them, and /strategies is a 500 naming the CatalogError."""
    monkeypatch.setattr(serve.psql, "default_dsn", lambda: "postgresql://nobody@127.0.0.1:9/nowhere")
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))
    code, data = _get(served + "/health")
    assert code == 200 and data["status"] == "degraded"
    assert "no strategies in" in data["error"] and "strategies" not in data
    code, data = _get(served + "/strategies")
    assert code == 500 and data["error"].startswith("CatalogError: no strategies in")


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
    code, data = _get(served + "/board?map=Ilios&weights=junk")    # a weight is id:value
    assert code == 400 and "id:value" in data["error"]
