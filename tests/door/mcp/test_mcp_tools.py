"""The tools in-process: query, db_status, roster, the board tools, the
compact infer, db_migrate and metrics against the built database; and,
with no database, query's refusals, the playbook writes' mirror, the Draft
a board tool hands its function, the readiness every door reports and how
query turns a cell into JSON and pages its rows. The one registry's family
order is test_mcp_registry's."""

import contextlib
import datetime
import decimal
import json
import os
import shutil

import psycopg
import pytest

from db import Refusal, psql
from db.psql import schema
from door.mcp import boards, lifecycle, solver, tools
from facts import board_facts, tables
from facts.draft import Draft
from inference import catalog
from tests.inference import FIXTURE_PLAYBOOK

# --- the tools against the built database ----------------------------------

@pytest.fixture(scope="module")
def ctx(db, dsn):
    return tools.Context(dsn=dsn)


@pytest.mark.invariant
def test_query_is_read_only(ctx):
    _text, data = ctx.call("query", sql="select count(*) from heroes")
    assert data["rows"][0][0] > 40
    text, data = ctx.call("query", sql="select generate_series(1, 300)")
    assert len(data["rows"]) == 200 and data["truncated"] is True
    assert text.endswith("\n(truncated: 200 rows shown)")
    _text, data = ctx.call("query", sql="select generate_series(1, 200)")
    assert len(data["rows"]) == 200 and data["truncated"] is False
    with pytest.raises(Refusal, match="read-only"):
        ctx.call("query", sql="delete from heroes")
    with pytest.raises(Refusal, match="read-only"):
        ctx.call("query", sql="select 1; drop table heroes")
    # what Postgres rejects is the caller's to fix too, answered in its words
    with pytest.raises(Refusal, match='query: column "nosuch" does not exist'):
        ctx.call("query", sql="select nosuch from heroes")


@pytest.mark.invariant
def test_db_status_and_roster(ctx):
    text, status = ctx.call("db_status")
    # 33: map_strategy went with counterpick.gg (migration 019)
    assert status["table_count"] >= 33 and status["counts"]["heroes"] > 40
    assert status["state"] == "current" and "state: current" in text
    assert status["counts"]["counters"] >= 100
    assert {s["source"] for s in status["snapshots"]} == {"blizzard"}
    _, roster = ctx.call("roster")
    assert any(h["name"] == "Ana" and h["portrait"] for h in roster["heroes"])
    assert any(m["name"] == "King's Row" and m["mode"] == "Hybrid" for m in roster["maps"])


@pytest.mark.invariant
def test_facts_and_infer_through_the_tools(ctx):
    text, data = ctx.call("facts", map="King's Row", red=["Zarya"], blue=["Ana"])
    assert data["count"] > 300 and text.startswith("[F1]")
    with pytest.raises(Refusal, match="unknown heroes"):
        ctx.call("facts", red=["Goku"])
    with pytest.raises(Refusal, match="unknown heroes"):
        ctx.call("reach", hero="Nosuchhero")
    text, data = ctx.call("infer", map="King's Row", red=["Zarya"], blue=["Ana"])
    assert len(data["blue"]) == 6 and "Ana" in data["blue"]
    assert "optimal comp" in text


@pytest.mark.invariant
def test_a_compact_infer_names_the_silent_heuristics_and_fits_a_reply(ctx):
    board = {"map": "King's Row", "red": ["Zarya"], "blue": ["Ana"]}
    _, full = ctx.call("infer", **board)
    text, data = ctx.call("infer", compact=True, **board)
    assert data["blue"] == full["blue"] and data["score"] == full["score"]
    silent = sorted(c["id"] for c in full["contributions"] if c.get("spread") is False)
    assert data["silent"] == silent
    assert data["idle"] == sum(1 for c in full["contributions"] if not c["applies"])
    assert data["terms"] == len(full["contributions"]) and "strategies" not in data
    assert len(data["largest"]) <= solver.COMPACT_TERMS
    assert len(text) + len(json.dumps(data)) < 10000


@pytest.mark.invariant
def test_db_migrate_is_idle_when_the_ledger_is_current(ctx):
    text, data = ctx.call("db_migrate")
    assert data["applied"] == [] and text.startswith("db_migrate: applied 0")


@pytest.mark.invariant
def test_query_runs_as_the_reader_role(ctx):
    _text, data = ctx.call("query", sql="select current_user, count(*) from heroes")
    assert data["rows"][0][0] == "matrix_reader" and data["rows"][0][1] > 0


# None of these touches the database, so they run without one (as CI does).

def test_query_refuses_file_and_server_reaching_sql_before_connecting():
    nowhere = tools.Context(dsn="postgresql://nowhere")
    for sql in ("select pg_read_file('/etc/passwd')", "select * from pg_ls_dir('.')",
                "COPY heroes TO PROGRAM 'id'", "select pg_sleep(10)"):
        with pytest.raises(Refusal, match=r"refuses|read-only"):
            nowhere.call("query", sql=sql)
    long = "select '%s'" % ("x" * (lifecycle.MAX_SQL_CHARS - 8))       # one character over
    assert len(long) == lifecycle.MAX_SQL_CHARS + 1
    with pytest.raises(Refusal, match="too long"):
        nowhere.call("query", sql=long)


def test_only_db_init_and_db_rebuild_create_the_cluster(tmp_path, monkeypatch):
    """The two tools that build the database reach psql.boot, which may
    create the embedded cluster; every other tool resolves through
    default_dsn, which never does. A dsn given to the Context is used as it
    is, and neither is asked."""
    monkeypatch.setenv("COUNTRIX_AUDIT", str(tmp_path / "audit.jsonl"))

    def refuse(said):
        def stub():
            raise psql.NoDatabaseError(said)
        return stub
    monkeypatch.setattr(psql, "boot", refuse("boot asked"))
    monkeypatch.setattr(psql, "default_dsn", refuse("resolver asked"))
    for name, asked in (("db_init", "boot asked"), ("db_rebuild", "boot asked"),
                        ("db_status", "resolver asked"), ("db_migrate", "resolver asked")):
        with pytest.raises(psql.NoDatabaseError, match=asked):
            tools.Context().call(name)
    with pytest.raises(psycopg.OperationalError):
        tools.Context(dsn="postgresql://nobody@127.0.0.1:9/nowhere").call("db_init")


def test_metrics_tool_serves_the_vocabulary():
    text, data = tools.Context(dsn="postgresql://nowhere").call("metrics")
    assert "team.coverage_share" in data["metrics"] and "team.coverage_share" in data["numeric"]
    assert "map.side" in data["text"] and "map.side" not in data["numeric"]
    assert text.splitlines()[0].startswith("team.")


def test_derive_strategies_is_idle_with_nothing_pending():
    text, data = tools.Context(dsn="postgresql://nowhere").call("derive_strategies")
    assert data["skipped"] == "nothing pending" and "nothing pending" in text
    assert data["deferred"] == 0


def test_every_playbook_write_mirrors_the_catalog_once(tmp_path, monkeypatch):
    """tune, add_strategy and infer_strategy each reload the strategies table
    once, after the write; derive_strategies with nothing derived connects to
    nothing."""
    for name in catalog.strategy_files(FIXTURE_PLAYBOOK):
        shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))
    monkeypatch.setenv("COUNTRIX_AUDIT", str(tmp_path / "audit.jsonl"))
    mirrored = []
    monkeypatch.setattr(catalog, "mirror", lambda cx, cat, directory=None: mirrored.append(
        (cx, len(cat))))

    class Offline(tools.Context):
        def connect(self):
            return contextlib.nullcontext("cx")
    ctx = Offline(dsn="postgresql://nowhere")
    heuristic = next(h for h in catalog.load() if h.kind == "heuristic")
    files = len(catalog.strategy_files(str(tmp_path)))
    ctx.call("tune", id=heuristic.id, field="weight", value=3, reason="a test")
    assert mirrored == [("cx", files)]
    ctx.call(
        "add_strategy", id="a-draft", name="A draft", kind="heuristic",
        body="Prose to infer from.", reason="a test")
    assert mirrored[1:] == [("cx", files + 1)]            # the new file is in the mirror
    ctx.call(
        "infer_strategy", id="a-draft", reason="a test", metric=heuristic.metric,
        direction="maximize", weight=1)
    assert len(mirrored) == 3
    assert not [h.id for h in catalog.load() if h.pending]
    _, data = ctx.call("derive_strategies")
    assert data["derived"] == [] and len(mirrored) == 3


def test_a_board_tool_hands_its_function_one_draft(tmp_path, monkeypatch):
    """The board tools share BOARD's five properties, first and in order, and
    each function gets them as one Draft: tuples, with what the call left out
    empty."""
    monkeypatch.setenv("COUNTRIX_AUDIT", str(tmp_path / "audit.jsonl"))
    seen = []

    class Stub:
        def to_dict(self):
            return {}

        def rendered(self):
            return ""

    class Offline(tools.Context):
        def connect(self):
            return contextlib.nullcontext("cx")
    monkeypatch.setattr(tables, "load", lambda cx: None)
    monkeypatch.setattr(board_facts, "generate", lambda world, draft: seen.append(draft) or Stub())
    Offline(dsn="postgresql://nowhere").call("facts", map="Ilios", red=["Ana"], bans=["Mei"])
    assert seen == [Draft("Ilios", ("Ana",), (), ("Mei",), "")]
    for name in ("facts", "infer", "evaluate", "board"):
        assert list(tools.REGISTRY.get(name).schema["properties"])[:5] == list(boards.BOARD)
    assert tools.REGISTRY.get("evaluate").schema["required"] == ["blue"]


def test_readiness_is_the_first_unmet_condition(monkeypatch):
    """One definition of ready for the entrypoint, compose, /health and the
    orchestrator: no tables, then a pending migration, then no heroes."""

    class Rows:
        def __init__(self, n):
            self.n = n

        def fetchone(self):
            return (self.n,)

    class Connection:
        def __init__(self, heroes):
            self.heroes = heroes

        def execute(self, sql, params=None):
            assert "heroes" in sql
            return Rows(self.heroes)

    def board(tables, pending, heroes):
        monkeypatch.setattr(schema, "table_count", lambda cx: tables)
        monkeypatch.setattr(schema, "pending", lambda cx: pending)
        return schema.state(Connection(heroes))

    assert board(0, ["001_initial_schema.sql"], 0) == "empty"
    assert board(35, ["099_future.sql"], 0) == "stale"
    assert board(35, ["099_future.sql"], 54) == "stale"
    assert board(35, [], 0) == "unfilled"
    assert board(35, [], 54) == "current"


def test_the_probe_exits_one_when_the_database_never_answers(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:9/nowhere")
    monkeypatch.setattr(schema, "CONNECT_TRIES", 2)
    monkeypatch.setattr(schema.time, "sleep", lambda seconds: None)
    assert schema.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "never became reachable" in captured.err
    assert "port 9" in captured.err                    # the last try's own error


def test_the_probe_exits_one_when_there_is_no_database(monkeypatch, capsys):
    """No DATABASE_URL and no cluster is no database to wait for: one line
    on stderr and exit 1 at once, which ends the container under set -e."""
    def nothing():
        raise psql.NoDatabaseError("nothing to point at")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(schema.psql, "default_dsn", nothing)
    assert schema.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "no database: nothing to point at" in captured.err


def test_a_query_cell_arrives_as_json():
    """A date as ISO text, an array or JSONB cell as JSON all the way down, and
    anything JSON has no type for as its text."""
    day = datetime.date(2026, 9, 24)
    assert lifecycle._cell(day) == "2026-09-24"
    assert lifecycle._cell(datetime.datetime(2026, 9, 24, 5, 0)) == "2026-09-24T05:00:00"
    assert lifecycle._cell([1, [day, "x"], None]) == [1, ["2026-09-24", "x"], None]
    assert lifecycle._cell({"when": day, 3: (True, 1.5)}) == {"when": "2026-09-24",
                                                         "3": [True, 1.5]}
    assert lifecycle._cell(decimal.Decimal("0.515")) == "0.515"


def test_a_query_page_says_truncated_exactly_when_a_row_is_left_out():
    """Past MAX_ROWS rows, or past the byte budget; never at exactly MAX_ROWS."""
    rows, truncated = lifecycle._page([(n,) for n in range(lifecycle.MAX_ROWS + 1)])
    assert len(rows) == lifecycle.MAX_ROWS and truncated is True
    rows, truncated = lifecycle._page([(n,) for n in range(lifecycle.MAX_ROWS)])
    assert len(rows) == lifecycle.MAX_ROWS and truncated is False
    # each cell is cut to MAX_CELL characters and an ellipsis before the budget
    # counts it: a row of 300 is about 600 KB, so the second row spends the MiB
    wide = ["x" * 5000] * 300
    rows, truncated = lifecycle._page([wide, wide, wide])
    assert len(rows) == 1 and truncated is True
    assert {len(cell) for cell in rows[0]} == {lifecycle.MAX_CELL + 1}
