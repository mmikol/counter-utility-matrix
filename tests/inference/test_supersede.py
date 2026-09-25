"""Latest wins in the pool: a superseded board's cancelled rounds; a
superseded pooled board that raises, keeps the pool and is not solved again
in this process; and a pooled board refused mid-pass, which cancels its
queued tasks all the same."""

import pytest

from inference.base import DEFAULT
from tests.inference.tracing import TRACED, Call, traced_board


def test_a_superseded_search_cancels_every_task_that_has_not_started(
        synthetic_world, scratch_playbook):
    """Each round first asks whether a newer board from the same client has
    replaced this one. Once one has, every task the board queued and no
    worker took is cancelled, and the round raises Superseded - a Refusal,
    which the doors answer 400 with no traceback."""
    from concurrent.futures import Future

    from db import Refusal
    from inference import parallel, supersede

    class Queued:
        def submit(self, task, *args):
            return Future()                   # queued: no worker has taken it
    newer = []
    watch = supersede.Watch(lambda: bool(newer))
    run = parallel.Run(Queued(), synthetic_world, scratch_playbook, None, 6, watch)
    split = parallel.Split(run, parallel.Spec(TRACED, 6, DEFAULT), 3)
    assert len(watch.futures) == 3 and not any(f.cancelled() for f in watch.futures)
    newer.append("the next board")
    with pytest.raises(supersede.Superseded):
        split.rank_roster()
    assert all(f.cancelled() for f in watch.futures)
    assert issubclass(supersede.Superseded, Refusal)


def test_a_superseded_board_is_not_solved_again_in_this_process(
        monkeypatch, synthetic_world, scratch_playbook):
    """A superseded pooled board is not a dead worker: it raises, the pool is
    kept, and the board is not run a second time here."""
    from inference import engine, supersede
    checks, trace = [], []

    def superseded():
        checks.append(1)
        return len(checks) > 4
    with pytest.raises(supersede.Superseded):
        traced_board(monkeypatch, synthetic_world, scratch_playbook, pooled=True,
                     brief=engine.Brief(superseded=superseded), trace=trace)
    assert len(trace) == 4 and Call("drop") not in trace


def test_a_pooled_board_that_refuses_mid_pass_cancels_every_task_it_queued(
        monkeypatch, synthetic_world, scratch_playbook):
    """A refusal is not a supersede, and no round's check raises it; the
    board still cancels every task its pass queued and no worker took, so a
    page that keeps asking for a board no six satisfies stacks no passes in
    the pool. The pool is kept."""
    from concurrent.futures import Future

    from db import Refusal
    from inference import engine, parallel
    queued, dropped = [], []

    class Queued:
        def submit(self, task, *args):
            future = Future()                 # queued: no worker has taken it
            queued.append(future)
            return future

    def refuse(split):
        raise Refusal("no composition satisfies the limits")
    monkeypatch.setattr(parallel, "available", lambda catalog=None: True)
    monkeypatch.setattr(parallel.POOL, "executor", lambda: parallel.Workers(Queued(), 6))
    monkeypatch.setattr(parallel.POOL, "drop", lambda: dropped.append("drop"))
    monkeypatch.setattr(parallel.Split, "rank_roster", refuse)
    with pytest.raises(Refusal, match="no composition satisfies the limits"):
        engine.board(synthetic_world, TRACED, catalog=scratch_playbook)
    assert len(queued) == 3 + 3                  # blue's and red's reference samples
    assert all(f.cancelled() for f in queued)
    assert dropped == []
