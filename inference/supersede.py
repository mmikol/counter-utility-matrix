"""Latest wins: a board a newer request from the same client replaced stops
at its next round instead of holding the pool.

Latest hands a server one ticket per request and client. Each board's
Watch holds its ticket and every task its searches submit; each round of
each search asks it first, and once the ticket is superseded it cancels
the tasks no worker has taken and raises Superseded. A board solved in
this process asks the same Watch, so it stops the same way.
"""

import threading
from collections.abc import Callable
from typing import Protocol

from db import Refusal


class Superseded(Refusal):
    """A board a newer request from the same client replaced before it was
    solved. It is answered as the caller's, a 400 with no traceback: the
    caller has already asked for the board it wants."""


class Latest:
    """Latest wins, per client: each board request takes a ticket under its
    client's name, and a ticket is superseded as soon as a newer one is taken
    under the same name. A server hands the ticket to board() as
    Brief.superseded, so a board the page has already moved past stops at
    its next round instead of holding the pool."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._newest: dict[str, int] = {}

    def take(self, client: str) -> Callable[[], bool]:
        """A new ticket for `client`: a check that turns true once another
        is taken under the same name."""
        with self._lock:
            mine = self._newest.get(client, 0) + 1
            self._newest[client] = mine

        def superseded() -> bool:
            with self._lock:
                return self._newest[client] != mine
        return superseded


# the page's boards, one lane per client, in whichever server solves them
LATEST = Latest()


class Cancellable(Protocol):
    """A submitted task as a Watch holds it: whatever it returns, it can be
    cancelled until a worker takes it."""

    def cancel(self) -> bool: ...


class Watch:
    """One board's check against being superseded, and every future its
    searches submitted. Each round of each search calls check(): once the
    board is superseded, the futures that have not started are cancelled and
    the round raises Superseded, so a stale board stops holding the pool."""

    def __init__(self, superseded: Callable[[], bool] | None = None) -> None:
        self.superseded = superseded
        self.futures: list[Cancellable] = []

    def check(self) -> None:
        """Raise Superseded, cancelling what has not started, once a newer
        request has replaced this board."""
        if self.superseded is not None and self.superseded():
            for future in self.futures:
                future.cancel()
            raise Superseded("a newer board from the same client superseded this one")
