"""Shared fixtures.

Three kinds of test:

    unit         pure functions - no database, no network
    invariant    properties the built database must hold
    validation   our data against a third party's published figures

Only the first runs anywhere. The other two default to the repo's own build
at db/psql/cluster - the same database `python -m db.mcp call db_rebuild` produces -
and skip themselves when there is nothing there, so `pytest` on a fresh clone
is still green. COUNTER_MATRIX_LOCAL_SERVER or DATABASE_URL override the target;
COUNTER_MATRIX_NO_DATABASE=1 runs the suite the way CI does, with no database.
"""

import os

import pytest


def _dsn():
    if os.environ.get("COUNTER_MATRIX_NO_DATABASE"):
        return None            # what CI sees: no cluster, the db-bound tests skip
    local = os.environ.get("COUNTER_MATRIX_LOCAL_SERVER")
    if not local and not os.environ.get("DATABASE_URL"):
        default = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "db", "psql", "cluster")
        if os.path.isdir(default):
            local = default
    if local:
        import pgserver

        return pgserver.get_server(os.path.abspath(local)).get_uri()
    return os.environ.get("DATABASE_URL")


@pytest.fixture(scope="session")
def dsn():
    """The connection string the suite runs against - with its password, which a
    connection's own `info.dsn` leaves out."""
    return _dsn()


@pytest.fixture(scope="session")
def db():
    dsn = _dsn()
    if not dsn:
        pytest.skip("no database: run `python -m db.mcp call db_rebuild` first")
    import psycopg

    try:
        connection = psycopg.connect(dsn)
    except psycopg.Error as error:
        pytest.skip("database unreachable: %s" % error)
    if connection.execute(
        "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
    ).fetchone()[0] == 0:
        pytest.skip("database is empty: run `python -m db.mcp call db_rebuild`")
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def rows(db):
    return lambda sql, *args: db.execute(sql, args or None).fetchall()


@pytest.fixture(scope="session")
def one(db):
    return lambda sql, *args: db.execute(sql, args or None).fetchone()[0]


@pytest.fixture(scope="session")
def fetch():
    """A network GET for validation tests; failures skip, never fail."""
    import requests

    session = requests.Session()
    session.headers.update({"User-Agent":
                            "counter-utility-matrix/0.1 (personal project; contact via repo)"})

    def get(url):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            pytest.skip("network: %s" % error)
    return get
