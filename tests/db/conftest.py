"""Fixtures the data layer's tests share."""

import psycopg
import pytest


@pytest.fixture()
def sandbox(db, dsn):
    """A connection run() may commit on: nothing lands."""
    connection = psycopg.connect(dsn)
    connection.commit = lambda: None
    yield connection
    connection.rollback()
    connection.close()
