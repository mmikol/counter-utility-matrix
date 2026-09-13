"""The verb ladder and its guardrails, against real throwaway clusters.

Each verb refuses the state it is not for and names the verb you wanted -
these tests are those promises, order-independent: the shared cluster comes
pre-initialised, and tests that need emptiness make their own. run_tools
is stubbed, so nothing here touches the network; pgserver's initdb is the
only real work, which keeps this CI-safe.
"""

import sys

import pytest

from data import orchestrator
from data import common
from data.db import schema

psycopg = pytest.importorskip("psycopg")
pgserver = pytest.importorskip("pgserver")


def connect(path):
    return psycopg.connect(pgserver.get_server(path).get_uri())


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    """A cluster with the schema applied and no data - post-`init` state."""
    path = str(tmp_path_factory.mktemp("verbs") / "cluster")
    with connect(path) as cx:
        schema.apply(cx, schema.read_migrations(), quiet=True)
    return path


@pytest.fixture()
def fresh(tmp_path):
    """A cluster with nothing in it at all - pre-`init` state."""
    return str(tmp_path / "cluster")


@pytest.fixture()
def run(monkeypatch):
    def make(path):
        calls = []
        monkeypatch.setattr(orchestrator, "run_tools",
                            lambda args, ctx: calls.append(args.command))

        def invoke(*argv):
            del calls[:]
            monkeypatch.setattr(sys, "argv",
                                ["orchestrator", *argv, "--local-server", path])
            orchestrator.main()
            return calls
        return invoke
    return make


def test_init_builds_the_schema_and_only_the_schema(run, fresh, capsys):
    run(fresh)("init")
    assert "no data" in capsys.readouterr().out
    with connect(fresh) as cx:
        assert cx.execute(
            "select count(*) from pg_tables where schemaname='public'"
        ).fetchone()[0] >= 30
        assert cx.execute("select count(*) from heroes").fetchone()[0] == 0
    with pytest.raises(SystemExit, match="rebuild.*starts over"):
        run(fresh)("init")


def test_inflate_and_update_dispatch_on_an_empty_schema(run, cluster):
    invoke = run(cluster)
    assert invoke("inflate") == ["inflate"]
    assert invoke("update") == ["update"]
    assert invoke() == ["update"]          # update is the default verb


def test_inflate_refuses_a_populated_database(run, cluster):
    with connect(cluster) as cx:
        cx.execute("insert into roles (code,name,source_id) values"
                   " ('tank','Tank',1) on conflict (code) do nothing")
        cx.execute("insert into subroles (role_id,code,name,passive_description,source_id)"
                   " select role_id,'x','X','',1 from roles where code='tank'"
                   " on conflict (code) do nothing")
        cx.execute("insert into heroes (slug,name,role_id,subrole_id,source_id)"
                   " select 'mei','Mei',role_id,subrole_id,1"
                   " from subroles where code='x'"
                   " on conflict (slug) do nothing")
        cx.commit()
    with pytest.raises(SystemExit, match="`update` is the verb"):
        run(cluster)("inflate")
    assert run(cluster)("update") == ["update"]   # update still welcome


def test_rebuild_refuses_a_partial_selection(run, cluster):
    with pytest.raises(SystemExit, match="always runs every tool"):
        run(cluster)("rebuild", "--only", "pull_kits")


def test_update_on_a_truly_empty_database_points_at_a_builder(run, fresh):
    pgserver.get_server(fresh)            # cluster exists, zero tables
    with pytest.raises(SystemExit, match="rebuild"):
        run(fresh)("update")


def test_restore_brings_recorded_recommendations_back(cluster, tmp_path):
    # a recorded comp survives export -> wipe -> restore, ids and all
    raw = str(tmp_path / "raw")
    with connect(cluster) as cx:
        cx.execute("insert into roles (code,name,source_id) values"
                   " ('tank','Tank',1) on conflict (code) do nothing")
        cx.execute("insert into subroles (role_id,code,name,"
                   "passive_description,source_id)"
                   " select role_id,'x','X','',1 from roles where code='tank'"
                   " on conflict (code) do nothing")
        cx.execute("insert into heroes (slug,name,role_id,subrole_id,source_id)"
                   " select 'mei','Mei',role_id,subrole_id,1"
                   " from subroles where code='x'"
                   " on conflict (slug) do nothing")
        cx.execute("delete from recommendations")
        rec_id, hero_id = cx.execute(
            "insert into recommendations (request,model,playstyle,reasoning,"
            " prompt,response,source_id) values"
            " ('q','m','brawl','r','p','{}',1)"
            " returning rec_id, (select hero_id from heroes where slug='mei')"
        ).fetchone()
        cx.execute("insert into recommendation_picks (rec_id,position,hero_id,"
                   "why,source_id) values (%s,1,%s,'walls',1)",
                   (rec_id, hero_id))
        cx.execute("insert into recommendation_evidence (rec_id,tag,"
                   "source_table,description,hero_id,source_id)"
                   " values (%s,'E1','t','d',%s,1)", (rec_id, hero_id))
        cx.commit()
        common.export(cx, raw_dir=raw)
        cx.execute("delete from recommendations")   # cascades to children
        cx.commit()

        assert schema.restore_recommendations(cx, raw_dir=raw) == 3
        assert cx.execute("select request from recommendations"
                          " where rec_id=%s", (rec_id,)).fetchone() == ("q",)
        # the sequence continues past the restored ids, no collision
        nxt = cx.execute("insert into recommendations (request,model,"
                         "playstyle,reasoning,prompt,response,source_id)"
                         " values ('q2','m','poke','r','p','{}',1)"
                         " returning rec_id"
                         ).fetchone()[0]
        assert nxt > rec_id
        # never merges into a database that already holds records
        assert schema.restore_recommendations(cx, raw_dir=raw) == 0
        cx.execute("delete from recommendations")
        cx.commit()
