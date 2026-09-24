"""The process pool the board splits its searches across: the round order,
a dying worker's board run again in this process, the pooled board against
the sequential one, the workers' start, and the two settings. A superseded
board's cancelled rounds are test_supersede's."""

import pytest

from inference import catalog
from inference.strategy import CatalogError
from tests.inference import FIXTURE_PLAYBOOK
from tests.inference.tracing import TRACED, Call, traced_board
from ui.facts.draft import Draft


def _timeless(board):
    """The board as data, less the seconds each result took."""
    d = board.to_dict()
    for value in d.values():
        if isinstance(value, dict) and "seconds" in value:
            value.pop("seconds")
    return d


def test_the_pooled_and_the_in_process_board_run_one_orchestration(
        monkeypatch, synthetic_world, scratch_playbook):
    """Pooled, the searches walk the rounds together in the order that keeps
    the pool full: blue and red rank their rosters and sweep, the two fills
    sweep on their seats' scales, blue and red merge and are solved, and only
    then does the countered case sweep against red's six - blue's best
    counter, and blue's pick filled on its scale. In this process no split is
    built. Both answer the same Board."""
    alone, none = traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=False)
    pooled, trace = traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=True)
    assert none == []
    enemy, ours = TRACED.red, TRACED.blue
    blue = {"locked": (), "enemy": enemy, "pool": 6}
    red = {"locked": (), "enemy": ours, "pool": 6}
    fill = {"locked": ours, "enemy": enemy, "pool": 6}
    red_fill = {"locked": enemy, "enemy": ours, "pool": 6}
    against = {"locked": (), "enemy": tuple(alone.red.blue), "pool": 4}
    answer = {"locked": ours, "enemy": tuple(alone.red.blue), "pool": 4}
    assert trace == [
        Call("rank_roster", **blue), Call("rank_roster", **red),
        Call("sweep", **blue), Call("sweep", **red),
        Call("sweep", **fill), Call("sweep", **red_fill),
        Call("merge", **blue), Call("merge", **red),
        Call("solved", **blue), Call("solved", **red),
        Call("sweep", **against), Call("sweep", **answer),
        Call("merge", **fill), Call("merge", **red_fill),
        Call("merge", **against), Call("merge", **answer),
        Call("solved", **fill), Call("solved", **red_fill),
        Call("solved", **against), Call("solved", **answer)]
    assert _timeless(pooled) == _timeless(alone)


def test_a_dying_worker_reruns_the_same_board_in_this_process(
        monkeypatch, capsys, synthetic_world, scratch_playbook):
    """A BrokenProcessPool anywhere in the pooled pass is noted on stderr, drops
    the pool and runs the board again here: at the first round, and after the
    two optimal seats are solved, the Board is the one this process answers
    alone."""
    alone, _ = traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=False)
    _, whole = traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=True)
    seated = [i for i, c in enumerate(whole) if c.what == "solved"][1] + 2
    for breaks_after in (1, seated):
        board, trace = traced_board(monkeypatch, synthetic_world, scratch_playbook,
                                    pooled=True, breaks_after=breaks_after)
        assert trace[breaks_after:] == [Call("drop")], breaks_after
        assert _timeless(board) == _timeless(alone), breaks_after
        assert "worker died (BrokenProcessPool: a worker died)" in capsys.readouterr().err


def test_a_board_without_the_countered_case_sends_none_of_its_rounds(
        monkeypatch, synthetic_world, scratch_playbook):
    """The page never reads the countered case, so its boards ask for none: no
    countered round reaches the pool, the Board holds none and the verdict no
    hedge. The rest is the board the MCP tool gets."""
    from inference import engine
    full, whole = traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=True)
    lean, trace = traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=True,
                               brief=engine.Brief(countered=False))
    assert trace == [c for c in whole if c.kw["pool"] != 4] != whole
    assert "your picks hold" in full.momentum["verdict"]
    assert lean.countered is None and lean.momentum["countered"] is None
    assert "your picks hold" not in lean.momentum["verdict"]
    assert ({k: v for k, v in _timeless(lean).items() if k not in ("countered", "momentum")}
            == {k: v for k, v in _timeless(full).items() if k not in ("countered", "momentum")})


@pytest.mark.invariant
def test_the_board_splits_its_solves_across_workers_and_agrees_with_one_process(world, monkeypatch):
    """Every search is cut into slices across the pool and merged here; the
    answer is byte-for-byte the sequential one, the board's weight overrides
    included (a worker loads the playbook from its files). The reference
    playbook is in force, so the sixes score and the overrides weigh
    something; a worker reads the playbook's folder from the environment it
    was spawned with, so the pool is started for it and dropped after."""
    from inference import engine, parallel
    if not parallel.available():
        pytest.skip("one core, or COUNTRIX_PARALLEL=0")
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    parallel.POOL.drop()
    try:
        assert parallel.warm() == parallel.worker_count() >= 6
        weights = {
            h.id: 10.0 if h.weight < 10 else 0.5
            for h in catalog.load() if h.kind == "heuristic"}
        assert weights                                 # or the overrides prove nothing
        draft = Draft("King's Row", ("Zarya", "Pharah"), ("Ana", "Reinhardt"), side="attack")
        split = engine.board(world, draft, brief=engine.Brief(weights=weights))
        assert split.blue.to_dict()["weights"] == weights     # the override reached the worker
        assert split.blue.unscored() is None                  # the six scored
        monkeypatch.setenv("COUNTRIX_PARALLEL", "0")
        assert not parallel.available()
        straight = engine.board(world, draft, brief=engine.Brief(weights=weights))
    finally:
        parallel.POOL.drop()

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


def test_warm_reports_a_worker_that_cannot_start_and_falls_back_to_one_process(
        monkeypatch, capsys):
    """A worker that cannot read the playbook fails its priming task. warm()
    says so on stderr, drops the pool and reports no workers, so the server
    boots and its boards solve in its own process."""
    from inference import parallel
    dropped = _priming_pool(monkeypatch, CatalogError("no strategy files in x/"))
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
