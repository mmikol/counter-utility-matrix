"""Fixtures the data layer's tests share."""

import dataclasses

import psycopg
import pytest

from db.data import wiki


@pytest.fixture()
def sandbox(db, dsn):
    """A connection run() may commit on: nothing lands."""
    connection = psycopg.connect(dsn)
    connection.commit = lambda: None
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture()
def instant_wiki(monkeypatch):
    """The wiki's request policies with no wait: their attempts, no backoff
    and no pause between pages."""
    for name in ("CARGO_POLICY", "ARTICLE_POLICY"):
        policy = getattr(wiki, name)
        monkeypatch.setattr(wiki, name, dataclasses.replace(policy, backoff=0, delay=0))
