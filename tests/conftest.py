"""Shared fixtures.

Two kinds of test:

    unit         pure functions - no database, no network
    invariant    properties the built database must hold

A unit test that needs a World takes synthetic_world, built by hand in
tests/synthetic.py. The second kind defaults to the repo's own build at
db/psql/cluster, the database `.venv/bin/python -m db.mcp call db_rebuild` produces,
and skips itself when it is absent. COUNTRIX_LOCAL_SERVER or DATABASE_URL
override the target; COUNTRIX_NO_DATABASE=1 runs the suite with no database,
as CI does.
"""

import os

import pytest

from db import DEFAULT_DB_DIR
from tests import synthetic


def _dsn():
    if os.environ.get("COUNTRIX_NO_DATABASE"):
        return None            # what CI sees: no cluster, the db-bound tests skip
    local = os.environ.get("COUNTRIX_LOCAL_SERVER")
    if not local and not os.environ.get("DATABASE_URL") and os.path.isdir(DEFAULT_DB_DIR):
        local = DEFAULT_DB_DIR
    if local:
        import pgserver

        return pgserver.get_server(os.path.abspath(local)).get_uri()
    return os.environ.get("DATABASE_URL")


@pytest.fixture(scope="session")
def dsn(db):
    """The connection string the suite runs against, password included (a
    connection's own `info.dsn` drops it). It rides on `db` so it skips the
    same way."""
    return _dsn()


@pytest.fixture(scope="session")
def db():
    dsn = _dsn()
    if not dsn:
        pytest.skip("no database: run `.venv/bin/python -m db.mcp call db_rebuild` first")
    import psycopg

    try:
        connection = psycopg.connect(dsn)
    except psycopg.Error as error:
        pytest.skip("database unreachable: %s" % error)
    if connection.execute(
        "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
    ).fetchone()[0] == 0:
        pytest.skip("database is empty: run `.venv/bin/python -m db.mcp call db_rebuild`")
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def world(db):
    """The World the facts and the inference tests read, built once per module.
    The load runs a read transaction; rolling it back leaves the session
    connection clean for the next fixture."""
    from ui.facts import tables

    w = tables.load(db)
    db.rollback()
    return w


@pytest.fixture()
def synthetic_world():
    """A fresh synthetic World for each test, which may change it: twelve
    released heroes, an announced one and three maps, and no database."""
    return synthetic.world()


@pytest.fixture(scope="session")
def rows(db):
    return lambda sql, *args: db.execute(sql, args or None).fetchall()


@pytest.fixture(scope="session")
def one(db):
    return lambda sql, *args: db.execute(sql, args or None).fetchone()[0]
