"""The board's server: its roster and facts speak what the MCP tools serve,
its settings are read when used, and its one write is a tune call through
the door. Its board and catalog are the inference service's handlers,
tested in tests/inference/test_inference_service.py. No HTTP server is spun
up - the handler is thin routing; tests/ui/test_board_server.py serves it."""

import pytest

from db import Refusal
from ui import board


@pytest.mark.invariant
def test_roster_endpoint_carries_portraits_and_maps(db):
    data, code = board.api_roster(db)
    assert code == 200
    assert {h["role"] for h in data["heroes"]} == {"tank", "damage", "support"}
    assert all(h["status"] in ("released", "announced") for h in data["heroes"])
    assert all(h["portrait"] for h in data["heroes"] if h["status"] == "released")
    assert any(m["name"] == "King's Row" for m in data["maps"])
    for h in data["heroes"]:                          # an announced hero rides in its role, dated
        if h["status"] == "announced":
            assert h["role"] in ("tank", "damage", "support") and "release_date" in h
    db.rollback()


@pytest.mark.invariant
def test_facts_endpoint_returns_the_board(db):
    data, code = board.api_facts(db, {"map": ["King's Row"], "red": ["Zarya", "Pharah"],
                                   "blue": ["Ana"]})
    assert code == 200 and data["count"] > 300
    keys = {f["key"] for f in data["facts"]}
    assert "team.coverage" in keys and "matchup.net_edges" in keys
    # UNDER-HEALED reads the supports' sustained healing, as the strategies do, not one cast
    data, code = board.api_facts(db, {"blue": ["Mercy", "Brigitte"], "red": ["Ana", "Moira"]})
    text = {(f["team"], f["key"]): f["text"] for f in data["facts"]}
    assert text["blue", "team.hps_supports"].endswith(" - UNDER-HEALED")
    assert "UNDER-HEALED" not in text["red", "team.hps_supports"]
    assert not any("UNDER-HEALED" in text[side, "team.heal_peak_supports"]
                   for side in ("blue", "red"))
    with pytest.raises(Refusal, match="Saitama"):      # the boundary answers it 400
        board.api_facts(db, {"red": ["Saitama"]})
    db.rollback()


@pytest.mark.invariant
def test_bans_ride_the_query_string(db):
    data, code = board.api_facts(db, {"map": ["King's Row"], "red": ["Zarya"],
                                      "bans": ["Widowmaker", "Sombra"]})
    assert code == 200 and data["bans"] == ["Widowmaker", "Sombra"]
    assert any(f["scope"] == "bans" for f in data["facts"])
    data, _ = board.api_roster(db)
    assert any(m["name"] == "King's Row" and m["sided"] for m in data["maps"])
    assert any(m["name"] == "Ilios" and not m["sided"] for m in data["maps"])
    db.rollback()


def test_the_board_writes_nothing_by_default(monkeypatch):
    # the test clears COUNTRIX_READ_ONLY itself, so an exported one cannot decide it
    monkeypatch.delenv("COUNTRIX_READ_ONLY", raising=False)
    assert board.read_only() is True


def test_a_service_url_that_is_not_http_is_refused(monkeypatch):
    # the board opens these with urlopen, which would read a file: URL as a path
    monkeypatch.setenv("COUNTRIX_INFERENCE_URL", "file:///etc/passwd")
    monkeypatch.setenv("COUNTRIX_MCP_URL", "ftp://x")
    with pytest.raises(ValueError, match="COUNTRIX_INFERENCE_URL must be an http or https URL"):
        board.inference_url()
    with pytest.raises(ValueError, match="COUNTRIX_MCP_URL must be an http or https URL"):
        board.mcp_url()
    monkeypatch.setattr(board.web, "LocalServer",
                        lambda *a: pytest.fail("the board bound its port"))
    with pytest.raises(SystemExit, match="COUNTRIX_INFERENCE_URL"):   # the board never starts
        board.main([])
    monkeypatch.setenv("COUNTRIX_INFERENCE_URL", "http://inference:8019/")
    assert board.inference_url() == "http://inference:8019"
    monkeypatch.setenv("COUNTRIX_MCP_URL", "https://data:8020/mcp")
    assert board.mcp_url() == "https://data:8020/mcp"
    monkeypatch.delenv("COUNTRIX_INFERENCE_URL")
    monkeypatch.delenv("COUNTRIX_MCP_URL")
    assert board.inference_url() == "" and board.mcp_url() == ""


# --- the board's one write: a weight stored through the tune tool ------------------


def test_storing_a_weight_is_a_tune_call_over_the_door(monkeypatch):
    """With an MCP URL set (the compose stack) the board sends one tools/call
    for `tune` - the id, the field, the rounded weight, the reason - and
    relays the tool's line or its refusal; bad input never reaches the door."""
    calls = []

    def fake_call_tool(url, name, arguments, token=None, timeout=60):
        calls.append((name, arguments))
        if arguments["id"] == "no-such":
            return board.web.CallReply("no strategy 'no-such'", None, True)
        return board.web.CallReply(
            "tuned %s: weight 1 -> %s\n- log line" % (arguments["id"], arguments["value"]),
            {"id": arguments["id"], "field": "weight", "old": 1.0, "new": "9.99"}, False)
    monkeypatch.setenv("COUNTRIX_MCP_URL", "http://data:8020/mcp")
    monkeypatch.setattr(board.web, "call_tool", fake_call_tool)
    data, code = board.api_weight({"id": "healing-floor", "weight": "9.994"})
    assert code == 200 and data["line"] == "tuned healing-floor: weight 1 -> 9.99"
    assert calls == [("tune", {"id": "healing-floor", "field": "weight", "value": 9.99,
                               "reason": board.STORE_REASON, "by": "the board"})]
    data, code = board.api_weight({"id": "no-such", "weight": 2})
    assert code == 400 and "no strategy" in data["error"]
    for bad in ({"id": "../escape", "weight": 2}, {"id": "healing-floor", "weight": "x"},
                {"id": "healing-floor", "weight": 11}, {"id": "healing-floor", "weight": [2]},
                {"id": "healing-floor", "weight": "nan"},
                {}, None):
        assert board.api_weight(bad)[1] == 400
    assert len(calls) == 2                                   # the refusals never knocked
    for low in (0, 0.25):                                    # under 1 is a weight, 0 switches off
        assert board.api_weight({"id": "healing-floor", "weight": low})[1] == 200
        assert calls[-1][1]["value"] == low


def test_the_boards_in_process_tool_calls_are_audited_as_the_board():
    # the context resolves its dsn lazily, so this opens no connection
    assert board.tool_context().client == "board"


@pytest.mark.invariant
def test_storing_a_weight_locally_runs_the_tune_tool_in_process(db, dsn, tmp_path, monkeypatch):
    """Without an MCP URL the same call goes through the tool registry: the
    file's weight changes, the tuning log says why, and the catalog is
    mirrored - here into a rolled-back transaction, on a private copy of
    the playbook."""
    import os
    import shutil

    from inference import catalog
    from tests.db.test_sources_from_cache import Sandbox
    from tests.inference import FIXTURE_PLAYBOOK
    for name in os.listdir(FIXTURE_PLAYBOOK):
        if name.endswith(".md"):
            shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    heuristic = next(h for h in catalog.load(FIXTURE_PLAYBOOK) if h.kind == "heuristic")
    monkeypatch.delenv("COUNTRIX_MCP_URL", raising=False)
    monkeypatch.setattr(board, "tool_context", lambda: Sandbox(dsn=dsn, client="board"))
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))   # the playbook in force
    data, code = board.api_weight({"id": heuristic.id, "weight": 7.25})
    assert code == 200 and data["line"].startswith("tuned %s: weight" % heuristic.id)
    assert data["change"]["new"] == "7.25"
    stored = next(h for h in catalog.load(str(tmp_path)) if h.id == heuristic.id)
    assert stored.weight == 7.25
    assert next(h for h in catalog.load(FIXTURE_PLAYBOOK)   # the reference file is untouched
                if h.id == heuristic.id).weight == heuristic.weight
    log = (tmp_path / "tuning-log.md").read_text(encoding="utf-8")
    assert board.STORE_REASON in log and heuristic.id in log and "[the board]" in log
    with pytest.raises(Refusal, match="no strategy"):  # the POST's boundary answers it 400
        board.api_weight({"id": "no-such-strategy", "weight": 2})
