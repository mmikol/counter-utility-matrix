"""A cursor and a connection that stand in for Postgres under a pull's store:
each statement is recorded as its text and its parameters, a read the test
names answers with the rows it gives, and any other statement reads back the
next id, as an upsert's RETURNING does. Every write lands: rowcount is 1."""

import itertools


class RecordingCursor:
    """`reads` pairs a statement's opening text with the rows it reads - a
    list, or a function of the statement's parameters. A statement no pair
    names reads back the next id from fetchone and nothing from fetchall."""

    def __init__(self, reads=()):
        self.statements = []
        self.reads = list(reads)
        self.rowcount = 1
        self._ids = itertools.count(1)
        self._rows = None

    def execute(self, query, params=()):
        text = query if isinstance(query, str) else query.as_string()
        self.statements.append((text, params))
        self._rows = None
        for opening, rows in self.reads:
            if text.startswith(opening):
                self._rows = rows(params) if callable(rows) else rows
                break
        return self

    def fetchone(self):
        if self._rows is None:
            return (next(self._ids),)
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows or ())

    def written(self, opening):
        """The parameters of every statement that opens with `opening`, in order."""
        return [params for text, params in self.statements if text.startswith(opening)]


class RecordingConnection:
    """Hands out RecordingCursors that share `reads`, and counts the commits."""

    def __init__(self, reads=()):
        self.reads = reads
        self.cursors = []
        self.commits = 0

    def cursor(self):
        self.cursors.append(RecordingCursor(self.reads))
        return self.cursors[-1]

    def commit(self):
        self.commits += 1
