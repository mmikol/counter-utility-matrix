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


def test_the_wire_refuses_a_team_of_seven_and_cuts_only_the_bans():
    """Seven picks on a team is no board a lobby seats, and cutting it to six
    would answer one the caller did not send: both doors refuse it. The bans
    are cut to five, as the page sends them."""
    from ui.facts.draft import parse_board
    seven = ["Ana", "Kiriko", "Lúcio", "Tracer", "Genji", "Sojourn", "Ashe"]
    for team in ("red", "blue"):
        with pytest.raises(Refusal, match="more than 6 %s picks" % team):
            parse_board({team: seven})
    draft = parse_board({"blue": seven[:6], "bans": seven})
    assert len(draft.blue) == 6 and len(draft.bans) == 5


def test_both_doors_bound_the_search_with_one_clamp():
    """A caller naming pool or top reaches the same bounds through the service
    as through the MCP tools: the engine owns the definition."""
    from inference.engine import POOL_CEILING, clamp_search
    assert clamp_search(None, None) == (6, 5)                  # the defaults
    assert clamp_search(0, 0) == (6, 5)                        # falsy reads as unset
    assert clamp_search(1, 0.5) == (2, 1)
    assert clamp_search(99, 99) == (POOL_CEILING, 20)
    assert clamp_search("8", "3") == (8, 3)                    # a query string is text
    for junk in ("x", [1], object()):                          # a refusal, not a crash
        with pytest.raises(Refusal, match="must be numbers"):
            clamp_search(junk)
    assert clamp_search([], []) == (6, 5)                      # empty is unset, like None


def test_the_pool_is_bounded_by_the_field_it_would_enumerate():
    """pool=12, the clamp's old maximum, ran the inference container out of
    memory: 1,345,960 legal sixes at about a kilobyte each against 2 GiB. The
    clamp caps the pool at the most candidates per role whose field fits the
    budget, and the default pool is far inside it."""
    from inference import engine
    assert engine.field_size(6) == 13_101 and engine.field_size(12) == 1_345_960
    pool, _ = engine.clamp_search(12)
    assert engine.field_size(pool) <= engine.FIELD_BUDGET < engine.field_size(pool + 1)
    assert pool == engine.POOL_CEILING == 10


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


def test_the_inference_service_listens_where_the_environment_says(monkeypatch):
    # the host and the port are read together, when the service starts
    monkeypatch.setenv("COUNTRIX_INFERENCE_HOST", "0.0.0.0")
    monkeypatch.setenv("COUNTRIX_INFERENCE_PORT", "8029")
    args = serve.command_line([])
    assert (args.host, args.port) == ("0.0.0.0", 8029)
    monkeypatch.delenv("COUNTRIX_INFERENCE_HOST")
    monkeypatch.delenv("COUNTRIX_INFERENCE_PORT")
    args = serve.command_line([])
    assert (args.host, args.port) == ("127.0.0.1", 8019)
    # the names it answers to beyond the local ones: `inference` in the compose stack
    assert args.allow_host == []
    assert serve.command_line(["--allow-host", "x", "--allow-host", "y"]).allow_host == ["x", "y"]


def test_board_forwards_to_a_named_inference_service(monkeypatch):
    calls, connected = [], []

    def fake_remote(path, query=None, payload=None):
        calls.append((path, query, payload))
        return {"forwarded": True}, 200

    monkeypatch.setenv("COUNTRIX_INFERENCE_URL", "http://inference:8019")
    monkeypatch.setattr(board, "remote", fake_remote)
    monkeypatch.setattr(board.psycopg, "connect", lambda *a, **k: connected.append(a))
    assert board.api_board({"map": ["Ilios"], "red": ["Zarya"], "blue": []}) == (
        {"forwarded": True}, 200)
    assert calls[-1] == ("/board", {"map": "Ilios", "side": "", "red": ["Zarya"],
                                    "blue": [], "bans": []}, None)
    board.api_board({"map": ["Ilios"], "weights": ["healing-floor:9.99", "x:12"]})
    assert calls[-1][1]["weights"] == ["healing-floor:9.99", "x:10"]  # clamped
    board.api_board({"map": ["Ilios"], "client": ["tab1"]})      # the page's lane rides along
    assert calls[-1][1]["client"] == "tab1"
    # a malformed weight is the caller's error, refused here and never forwarded
    forwarded = len(calls)
    with pytest.raises(Refusal, match="id:value"):
        board.api_board({"map": ["Ilios"], "weights": ["junk"]})
    assert len(calls) == forwarded
    assert connected == []                  # a forwarded board opens no connection
    # the status rides along now: a 502 from the service is not served as a 200
    assert board.api_strategies() == ({"forwarded": True}, 200)


def test_board_reports_an_unreachable_inference_service(monkeypatch, capsys):
    monkeypatch.setenv("COUNTRIX_INFERENCE_URL", "http://127.0.0.1:9")
    data, code = board.remote("/health")
    assert code == 502 and "unreachable" in data["error"]
    # the 502 is the page's; the reason is the container log's too
    assert capsys.readouterr().err.startswith(
        "countrix board: the inference service at http://127.0.0.1:9 did not answer /health: ")


# --- served ------------------------------------------------------------------------------

@pytest.fixture()
def served():
    import threading

    from db import web
    server = web.LocalServer(("127.0.0.1", 0), serve.Handler, ["inference"])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


def _get(url, headers=None):
    import json
    import urllib.error
    import urllib.request
    try:
        request = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_the_service_answers_only_to_the_names_it_is_called_by(served, monkeypatch):
    """The board calls the service as http://inference:8019, so the compose
    stack starts it with --allow-host inference; any other name is refused
    before a route runs."""
    monkeypatch.setattr(serve.psql, "default_dsn", lambda: "postgresql://nobody@127.0.0.1:9/nowhere")
    assert _get(served + "/health", {"Host": "evil.example"}) == (
        403, {"error": "host or origin not allowed"})
    assert _get(served + "/health", {"Host": "inference:8019"})[0] == 200
    assert _get(served + "/health", {"Origin": "http://evil.example"})[0] == 403


def test_a_solve_leaves_a_line_on_stderr_and_health_none(served, monkeypatch, capsys):
    import re
    monkeypatch.setattr(serve.psql, "default_dsn", lambda: "postgresql://nobody@127.0.0.1:9/nowhere")
    capsys.readouterr()
    assert _get(served + "/health")[0] == 200
    assert capsys.readouterr().err == ""
    assert _get(served + "/board?map=Ilios")[0] == 500             # no database: still a line
    assert re.search(r'"GET /board\?map=Ilios HTTP/1.1" 500 \d+\.\d\ds$',
                     capsys.readouterr().err.rstrip())


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
    assert code == 200 and data["rank"] == (None if data["unscored"] else 1)
    code, data = _get(served + "/evaluate?map=Ilios&blue=Ana")
    assert code == 400 and "error" in data
    code, data = _get(served + "/board?map=Ilios&weights=junk")    # a weight is id:value
    assert code == 400 and "id:value" in data["error"]
