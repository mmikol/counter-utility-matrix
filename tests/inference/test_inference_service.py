"""The inference engine as a service: its handlers speak the same results
the engine returns in-process, the board calls them in its own process or
forwards to the service when told to, and both paths answer alike."""

from urllib.parse import quote

import pytest

from db import Refusal
from inference import catalog, serve
from ui import board


def test_both_doors_bound_the_search_with_one_clamp():
    """A caller naming pool or top reaches the same bounds through the service
    as through the MCP tools: the engine owns the definition. Only a knob left
    out takes the default; 0 is a number like any other, clamped to the floor
    whether it comes as an int or as a query string's text."""
    from inference.engine import POOL_CEILING, clamp_search
    assert clamp_search(None, None) == (6, 5)                  # the defaults
    assert clamp_search(0, 0) == (2, 1)                        # 0 is the floor, not unset
    assert clamp_search("0", "0") == (2, 1)                    # on every door
    assert clamp_search(-3, -3) == (2, 1)
    assert clamp_search(1, 0.5) == (2, 1)
    assert clamp_search(99, 99) == (POOL_CEILING, 20)
    assert clamp_search("8", "3") == (8, 3)                    # a query string is text
    for junk in ("x", [1], [], object()):                      # a refusal, not a crash
        with pytest.raises(Refusal, match="must be numbers"):
            clamp_search(junk)


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
    db.rollback()


@pytest.mark.invariant
def test_the_board_handler_serves_both_seats_and_the_current_comp(db):
    """What the page's board shows, on either path: both seats' optimal on
    opposite sides, the current comp partial until blue holds six and
    evaluated once it does, and no countered case."""
    for side, other in (("attack", "defense"), ("defense", "attack")):
        data, code = serve.handle_board(db, {
            "map": ["King's Row"], "red": ["Zarya"], "blue": ["Ana"], "side": [side]})
        assert code == 200 and data["side"] == side
        assert data["blue"]["kind"] == "infer" and len(data["blue"]["blue"]) == 6
        assert data["red"]["seat"] == "red" and data["red"]["side"] == other
        assert data["current"]["partial"] and data["current"]["blue"] == ["Ana"]
        assert data["blue"]["cited"] and all(p["evidence"] for p in data["blue"]["picks"])
        assert data["countered"] is None                   # the page never reads it
    data, code = serve.handle_board(db, {
        "blue": ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"]})
    current = data["current"]
    assert code == 200 and current["kind"] == "evaluate"
    assert current["rank"] is None if current["unscored"] else current["rank"] >= 1
    with pytest.raises(Refusal, match="banned"):          # the boundary answers it 400
        serve.handle_board(db, {"red": ["Zarya"], "blue": ["Ana"], "bans": ["Ana"]})
    db.rollback()


def test_a_refused_board_supersedes_nothing():
    """The service reads the whole query before it takes the client's lane,
    so a board its parse refuses - a junk weight, a junk pool, a seventh
    pick - leaves the board still solving in that lane alone. No database
    is reached: each is refused before the World loads."""
    from inference import supersede
    ticket = supersede.LATEST.take("tab1")
    seven = ["Ana", "Ashe", "Baptiste", "Cassidy", "Genji", "Kiriko", "Mercy"]
    for refused in ({"weights": ["junk"]}, {"pool": ["x"]}, {"red": seven}):
        with pytest.raises(Refusal):
            serve.handle_board(None, {**refused, "client": ["tab1"]})
    assert ticket() is False


@pytest.mark.invariant
def test_health_reports_the_catalog_and_the_database(monkeypatch, dsn):
    monkeypatch.setattr(serve.psql, "default_dsn", lambda: dsn)
    data, code = serve.handle_health()
    assert code == 200 and data["strategies"] == len(catalog.load())
    assert data["status"] == "ok" and data["heroes"] > 40


def test_a_host_without_pgserver_is_told_to_set_database_url(monkeypatch, tmp_path):
    """The image and CI carry no pgserver. With no DATABASE_URL either there is
    no database, even beside a built cluster, and the one useful answer names
    the variable to set: a NoDatabaseError, which /health reports as
    degraded. The cluster here is a PG_VERSION file, so the test reaches the
    missing pgserver on every host."""
    (tmp_path / "PG_VERSION").write_text("16\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(serve.psql, "DEFAULT_DB_DIR", str(tmp_path))
    monkeypatch.setattr(serve.psql, "pgserver", None)
    with pytest.raises(serve.psql.NoDatabaseError,
                       match=r"pgserver is not installed.*DATABASE_URL"):
        serve.psql.default_dsn()
    data, code = serve.handle_health()
    assert code == 200 and data["status"] == "degraded" and "DATABASE_URL" in data["error"]


def test_a_probe_with_no_cluster_is_degraded_and_creates_none(monkeypatch, tmp_path):
    """default_dsn resolves and never creates: with no DATABASE_URL and no
    cluster built it raises NoDatabaseError before pgserver is asked, and
    /health answers degraded with the variable to set. Only db_init and
    db_rebuild create a cluster, through psql.boot."""
    cluster = tmp_path / "cluster"

    class NoServer:
        @staticmethod
        def get_server(pgdata):
            raise AssertionError("the resolver asked pgserver for %s" % pgdata)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(serve.psql, "DEFAULT_DB_DIR", str(cluster))
    monkeypatch.setattr(serve.psql, "pgserver", NoServer)
    with pytest.raises(serve.psql.NoDatabaseError, match="db_rebuild"):
        serve.psql.default_dsn()
    data, code = serve.handle_health()
    assert code == 200 and data["status"] == "degraded" and "DATABASE_URL" in data["error"]
    assert not cluster.exists()


def test_an_emptied_pid_file_degrades_health(monkeypatch):
    """A process killed while writing pgserver's pid file leaves it empty, and
    the next first touch reads it as a JSONDecodeError: one of the ways the
    database is out of reach, so /health answers 200 and degraded."""
    import json

    def emptied():
        raise json.JSONDecodeError("Expecting value", "", 0)
    monkeypatch.setattr(serve.psql, "default_dsn", emptied)
    data, code = serve.handle_health()
    assert code == 200 and data["status"] == "degraded" and "Expecting value" in data["error"]


def test_the_first_touch_holds_the_lock_and_leaves_the_pid_file_alone(monkeypatch, tmp_path):
    """The first touch asks pgserver once, under the process's own lock, so
    two threads cannot interleave its pid file; an emptied file is pgserver's
    and is reported, never rewritten, and the lock is free afterwards."""
    import json

    (tmp_path / "PG_VERSION").write_text("16\n")
    pids = tmp_path / ".handle_pids.json"
    pids.write_text("")
    held = []

    class Server:
        @staticmethod
        def get_server(pgdata):
            held.append(serve.psql._FIRST_TOUCH.locked())
            raise json.JSONDecodeError("Expecting value", "", 0)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(serve.psql, "DEFAULT_DB_DIR", str(tmp_path))
    monkeypatch.setattr(serve.psql, "pgserver", Server)
    with pytest.raises(json.JSONDecodeError):
        serve.psql.default_dsn()
    assert held == [True]
    assert pids.read_text() == ""
    assert not serve.psql._FIRST_TOUCH.locked()


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


def test_the_board_forwards_a_query_as_received(monkeypatch):
    """With a service named, the page's query reaches it unchanged - the
    client, the weights, a weight the service will refuse and one it will
    clamp - and the service's reply is the board's; nothing is parsed here
    and no connection opens."""
    calls, connected = [], []

    def fake_remote(path, query=None, payload=None):
        calls.append((path, query, payload))
        return {"forwarded": True}, 200

    monkeypatch.setenv("COUNTRIX_INFERENCE_URL", "http://inference:8019")
    monkeypatch.setattr(board, "remote", fake_remote)
    monkeypatch.setattr(board.psycopg, "connect", lambda *a, **k: connected.append(a))
    query = {"map": ["Ilios"], "red": ["Zarya"], "client": ["tab1"], "weights": ["x:12", "junk"]}
    assert board.api_board(query) == ({"forwarded": True}, 200)
    assert calls == [("/board", {"map": ["Ilios"], "red": ["Zarya"], "client": ["tab1"],
                                 "weights": ["x:12", "junk"]}, None)]
    assert connected == []                  # a forwarded board opens no connection
    # the status rides along: a 502 from the service is not served as a 200
    assert board.api_strategies() == ({"forwarded": True}, 200)
    assert calls[-1] == ("/strategies", None, None)


def test_board_reports_an_unreachable_inference_service(monkeypatch, capsys):
    monkeypatch.setenv("COUNTRIX_INFERENCE_URL", "http://127.0.0.1:9")
    data, code = board.remote("/health")
    assert code == 502 and "unreachable" in data["error"]
    # the 502 is the page's; the reason is the container log's too
    assert capsys.readouterr().err.startswith(
        "countrix board: the inference service at http://127.0.0.1:9 did not answer /health: ")


class _Answered:
    """What a stubbed urlopen answers: a body and a status."""

    def __init__(self, body, status):
        self.body, self.status = body, status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_an_inference_answer_that_is_not_json_is_a_502(monkeypatch):
    import urllib.request
    monkeypatch.setenv("COUNTRIX_INFERENCE_URL", "http://inference:8019")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda request, timeout: _Answered(b"<html>", 200))
    assert board.remote("/strategies") == (
        {"error": "the inference service answered 200 with no JSON object"}, 502)


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


@pytest.mark.invariant
def test_the_board_answers_the_same_in_process_and_through_the_service(served, monkeypatch, dsn):
    """The page's board is serve.handle_board on either path: the same query
    under a weight solved in the board's process and on the served service
    answers the same status and body, the seconds aside, and a malformed
    weight the same 400 in the service's words. Both solve in this process,
    under the reference playbook, so the weight rides on a heuristic; the
    pooled board's agreement with this one is test_parallel's."""
    import json

    from db import web
    from tests.inference import FIXTURE_PLAYBOOK, timeless
    monkeypatch.setattr(serve.psql, "default_dsn", lambda: dsn)   # board.psql is the same module
    monkeypatch.setenv("COUNTRIX_PARALLEL", "0")
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    heuristic = next(s for s in catalog.load(FIXTURE_PLAYBOOK) if s.kind == "heuristic")

    def in_process(query):
        monkeypatch.delenv("COUNTRIX_INFERENCE_URL", raising=False)
        return board.api_board(query)

    def on_the_service(query):
        monkeypatch.setenv("COUNTRIX_INFERENCE_URL", served)
        return board.api_board(query)
    query = {
        "map": ["King's Row"], "red": ["Zarya"], "blue": ["Ana"], "side": ["attack"],
        "weights": ["%s:3" % heuristic.id]}
    here, there = in_process(query), on_the_service(query)
    assert here.status == there.status == 200
    sent = json.loads(json.dumps(here.body))             # as the board's handler sends it
    assert heuristic.weight != 3 and sent["blue"]["weights"][heuristic.id] == 3   # it rode
    assert timeless(sent) == timeless(there.body)
    junk = {"map": ["Ilios"], "weights": ["junk"]}
    with pytest.raises(Refusal) as refused:
        in_process(junk)
    reply = on_the_service(junk)
    assert reply.status == 400 and web.failure(refused.value) == reply
