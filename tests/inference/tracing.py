"""The pool's rounds as a trace: board() run for real in this process on the
synthetic World, with a recording Split standing in for the workers. The
pool tests read the round order and a dying worker's rerun from it, the
supersede tests a stale board that stops and keeps the pool."""

from concurrent.futures.process import BrokenProcessPool

from ui.facts.draft import Draft


class Call:
    """One round of the pool, as the trace records it."""

    def __init__(self, what, **kw):
        self.what, self.kw = what, kw

    def __eq__(self, other):
        return (self.what, self.kw) == (other.what, other.kw)

    def __repr__(self):
        return "%s(%s)" % (self.what, ", ".join("%s=%r" % kv for kv in sorted(self.kw.items())))


# red revealed and one blue pick locked on a sided map: all four searches run
TRACED = Draft("Harbor Gate", ("Anvil",), ("Balm",), side="attack")


def traced_board(
        monkeypatch, world, playbook, *, pooled, breaks_after=None, brief=None, trace=None):
    """board() for real, in this process, on the synthetic World, under
    `brief`. Pooled, a recording Split with the real one's constructor stands
    in for the workers: it checks the board's watch and traces each round,
    hands back None from solved() and swept() so each seat searches for
    itself, and after `breaks_after` rounds a worker dies. Only the pool
    module's public names are patched. -> (the Board, the trace)."""
    from inference import engine, parallel
    trace = [] if trace is None else trace

    class Split:
        started = None                  # the seat searches for itself, and times it

        def __init__(self, run, spec, slices, bounds=None, standing=None):
            self.run, self.spec, self.bounds, self.standing = run, spec, bounds, standing

        def _round(self, name):
            self.run.watch.check()
            seat = self.spec.draft
            trace.append(Call(name, locked=seat.blue, enemy=seat.red, pool=self.spec.pool_size))
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
    monkeypatch.setattr(parallel.POOL, "drop", lambda: trace.append(Call("drop")))
    monkeypatch.setattr(parallel, "Split", Split)
    return engine.board(world, TRACED, catalog=playbook, brief=brief), trace
