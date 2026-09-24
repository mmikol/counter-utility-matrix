"""The process pool the board splits its searches across: the round order,
a dying worker's board run again in this process, the pooled board against
the sequential one, the workers' start, and the two settings."""

from concurrent.futures.process import BrokenProcessPool

import pytest

from inference import catalog
from ui.facts.draft import Draft


class _Call:
    """One round of the pool, as the trace records it."""

    def __init__(self, what, **kw):
        self.what, self.kw = what, kw

    def __eq__(self, other):
        return (self.what, self.kw) == (other.what, other.kw)

    def __repr__(self):
        return "%s(%s)" % (self.what, ", ".join("%s=%r" % kv for kv in sorted(self.kw.items())))


# red revealed and one blue pick locked on a sided map: all four searches run
TRACED = Draft("Harbor Gate", ("Anvil",), ("Balm",), side="attack")


def _traced_board(monkeypatch, world, playbook, *, pooled, breaks_after=None):
    """board() for real, in this process, on the synthetic World. Pooled, a
    recording Split with the real one's constructor stands in for the workers:
    it traces each round, hands back None from solved() and swept() so each
    seat searches for itself, and after `breaks_after` rounds a worker dies.
    Only the pool module's public names are patched. -> (the Board, the
    trace)."""
    from inference import engine, parallel
    trace = []

    class Split:
        def __init__(self, pool, world, catalog, spec, weights, top, slices,
                     bounds=None, standing=None):
            self.spec, self.bounds, self.standing = spec, bounds, standing

        def _round(self, name):
            seat = self.spec.draft
            trace.append(_Call(name, locked=seat.blue, enemy=seat.red, pool=self.spec.pool_size))
            if breaks_after is not None and len(trace) >= breaks_after:
                raise BrokenProcessPool("a worker died")

        def rank_roster(self):
            self._round("rank_roster")

        def sweep(self):
            self._round("sweep")

        def merge(self):
            self._round("merge")

        def solved(self):
            self._round("solved")

        def swept(self):
            self._round("swept")

    monkeypatch.setattr(parallel, "available", lambda catalog=None: pooled)
    monkeypatch.setattr(parallel.POOL, "executor",
                        lambda: parallel.Workers(executor=None, size=6))
    monkeypatch.setattr(parallel.POOL, "drop", lambda: trace.append(_Call("drop")))
    monkeypatch.setattr(parallel, "Split", Split)
    return engine.board(world, TRACED, catalog=playbook), trace


def _timeless(board):
    """The board as data, less the seconds each result took."""
    d = board.to_dict()
    for value in d.values():
        if isinstance(value, dict) and "seconds" in value:
            value.pop("seconds")
    return d


def test_the_pooled_and_the_in_process_board_run_one_orchestration(
        monkeypatch, synthetic_world, scratch_playbook):
    """Pooled, the four searches walk the rounds together in the order that
    keeps the pool full: blue and red rank their rosters and sweep, the fill
    sweeps on blue's scale, blue and red merge and are solved, and only then
    does the countered case sweep, against red's six. In this process no
    split is built. Both answer the same Board."""
    alone, none = _traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=False)
    pooled, trace = _traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=True)
    assert none == []
    enemy, ours = TRACED.red, TRACED.blue
    blue = {"locked": (), "enemy": enemy, "pool": 6}
    red = {"locked": (), "enemy": ours, "pool": 6}
    fill = {"locked": ours, "enemy": enemy, "pool": 6}
    countered = {"locked": (), "enemy": tuple(alone.red.blue), "pool": 4}
    assert trace == [
        _Call("rank_roster", **blue), _Call("rank_roster", **red),
        _Call("sweep", **blue), _Call("sweep", **red), _Call("sweep", **fill),
        _Call("merge", **blue), _Call("merge", **red),
        _Call("solved", **blue), _Call("solved", **red),
        _Call("sweep", **countered), _Call("merge", **fill), _Call("merge", **countered),
        _Call("solved", **fill), _Call("solved", **countered)]
    assert _timeless(pooled) == _timeless(alone)


def test_a_dying_worker_reruns_the_same_board_in_this_process(
        monkeypatch, synthetic_world, scratch_playbook):
    """A BrokenProcessPool anywhere in the pooled pass drops the pool and runs
    the board again here: at the first round, and after the two optimal seats
    are solved, the Board is the one this process answers alone."""
    alone, _ = _traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=False)
    _, whole = _traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=True)
    seated = [i for i, c in enumerate(whole) if c.what == "solved"][1] + 2
    for breaks_after in (1, seated):
        board, trace = _traced_board(monkeypatch, synthetic_world, scratch_playbook,
                                     pooled=True, breaks_after=breaks_after)
        assert trace[breaks_after:] == [_Call("drop")], breaks_after
        assert _timeless(board) == _timeless(alone), breaks_after


@pytest.mark.invariant
def test_the_board_splits_its_solves_across_workers_and_agrees_with_one_process(world, monkeypatch):
    """Every search is cut into slices across the pool and merged here; the
    answer is byte-for-byte the sequential one, the board's weight overrides
    included (a worker loads the playbook from its files)."""
    from inference import engine, parallel
    if not parallel.available():
        pytest.skip("one core, or COUNTRIX_PARALLEL=0")
    assert parallel.warm() == parallel.worker_count() >= 6
    weights = {
        h.id: 10.0 if h.weight < 10 else 0.5 for h in catalog.load() if h.kind == "heuristic"}
    draft = Draft("King's Row", ("Zarya", "Pharah"), ("Ana", "Reinhardt"), side="attack")
    split = engine.board(world, draft, weights=weights)
    assert split.blue.to_dict()["weights"] == weights         # the override reached the worker
    monkeypatch.setenv("COUNTRIX_PARALLEL", "0")
    assert not parallel.available()
    straight = engine.board(world, draft, weights=weights)

    def timeless(b):
        d = b.to_dict()
        for key in ("blue", "red", "current", "red_current", "fill", "countered"):
            if d.get(key):
                d[key].pop("seconds", None)
        return d
    assert timeless(split) == timeless(straight)
    first_line = lambda b: b.rendered().split("\n")[0]   # noqa: E731
    assert first_line(split) == first_line(straight)
    assert parallel.available(catalog=[]) is False   # a caller's catalog stays in-process


def _priming_pool(monkeypatch, outcome):
    """warm() against a stand-in pool of six whose every priming task ends in
    `outcome` - a result, or an exception raised in the worker. Returns what
    the pool was asked to drop."""
    from concurrent.futures import Future

    from inference import parallel
    dropped = []

    class Executor:
        def submit(self, fn, *args):
            future = Future()
            if isinstance(outcome, Exception):
                future.set_exception(outcome)
            else:
                future.set_result(outcome)
            return future
    monkeypatch.setattr(parallel, "available", lambda catalog=None: True)
    monkeypatch.setattr(parallel.POOL, "executor", lambda: parallel.Workers(Executor(), 6))
    monkeypatch.setattr(parallel.POOL, "drop", lambda: dropped.append("drop"))
    return dropped


def test_warm_reports_a_worker_that_cannot_start_and_falls_back_to_one_process(monkeypatch,
                                                                                capsys):
    """A worker that cannot read the playbook fails its priming task. warm()
    says so on stderr, drops the pool and reports no workers, so the server
    boots and its boards solve in its own process."""
    from inference import parallel
    dropped = _priming_pool(monkeypatch, catalog.CatalogError("no strategy files in x/"))
    assert parallel.warm() == 0
    assert ("the solver workers did not start (CatalogError: no strategy files in x/);"
            " boards solve in this process") in capsys.readouterr().err
    assert dropped == ["drop"]


def test_warm_returns_the_worker_count_when_every_worker_starts(monkeypatch):
    from inference import parallel
    dropped = _priming_pool(monkeypatch, 4242)
    assert parallel.warm() == 6 and dropped == []


def test_countrix_workers_sets_the_worker_count(monkeypatch):
    # read when the pool starts, so no pool is spawned to read it here
    from inference import parallel
    monkeypatch.setenv("COUNTRIX_WORKERS", "3")
    assert parallel.worker_count() == 3
    for cores, count in ((16, parallel.WORKER_CEILING), (2, 6)):
        monkeypatch.setattr(parallel.os, "cpu_count", lambda cores=cores: cores)
        for junk in ("0", "x"):
            monkeypatch.setenv("COUNTRIX_WORKERS", junk)
            assert parallel.worker_count() == count, (cores, junk)
        monkeypatch.delenv("COUNTRIX_WORKERS")
        assert parallel.worker_count() == count, cores


def test_countrix_parallel_off_keeps_the_board_in_one_process(monkeypatch):
    # read on every board: the switch holds from the next call
    from inference import parallel
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 4)
    monkeypatch.setenv("COUNTRIX_PARALLEL", "1")
    assert parallel.available() is True
    for off in ("0", "no", "False"):
        monkeypatch.setenv("COUNTRIX_PARALLEL", off)
        assert parallel.available() is False, off
