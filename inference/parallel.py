"""The process pool the board splits its searches across.

CPython holds the GIL for this pure-Python work, so parallelism means
processes: a pool of workers, spawned once and kept - the servers that call
this are threaded, and forking a threaded process is unsafe. Each search
runs in four rounds, a slice per worker: the reference sample, for the low
and high each heuristic takes on this board; the sample again, scored under
those bounds, for each hero's standing, which ranks the pools; the
enumeration, prepared and scored; then one worker ranks and refines the
merged field. Only verdicts cross - hero ids, score, tie-break - and slices
partition their round, so nothing depends on how the work was split.

A board runs up to six searches. Blue's and red's go first. A seat's fill
is that seat's board (same map, side, enemies and bans), so it takes the
seat's bounds and standing and draws no sample of its own; the countered
case's two - blue's best counter to red's six, and blue's picks filled on
its scale - follow red's six. A full six is ranked against the field its
seat's search already swept.

Each round first asks the board's Watch (inference.supersede) whether a
newer request replaced the board; the Watch sees every task the searches
submit, so a superseded board's queued tasks are cancelled.

The world crosses as bytes pickled once and cached per worker; so is the
playbook, reread when a file changes. Off with COUNTRIX_PARALLEL=0 (read on
every board), on one core, or with a catalog the caller supplied (a worker
loads the playbook from its files). The task functions are top-level, so a
spawned worker finds them by module path.
"""

import concurrent.futures
import hashlib
import multiprocessing
import os
import pickle  # nosec B403  # pickles cross only from this process to the workers it spawned
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ProcessPoolExecutor
from typing import Concatenate, NamedTuple

from facts.draft import Draft
from facts.model import World
from inference import catalog as catalog_module
from inference.scale import Standing, Tally, reference_bounds, reference_standing
from inference.scoring import Bounds, Candidate, Interval
from inference.solver import Solved, Solver, Swept
from inference.strategy import Strategy
from inference.supersede import Watch

WORKER_CEILING = 12          # a worker holds about 70 MB, and past a dozen slices the
                             # rounds' own overhead eats what a finer slice saves


def worker_count() -> int:
    """Six workers, or one per core where there are more, capped at
    WORKER_CEILING. COUNTRIX_WORKERS overrides; the pool reads it when it
    starts."""
    override = os.environ.get("COUNTRIX_WORKERS", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    return max(6, min(os.cpu_count() or 1, WORKER_CEILING))


class Workers(NamedTuple):
    """The live process pool and the worker count it was created with."""
    executor: ProcessPoolExecutor
    size: int


class _Pool:
    """The parent's side of the process pool: the executor, created on first
    use and spawned, not forked, with the worker count it was created with,
    under one lock; and the world pickled once for a run of tasks, under its
    own."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor: ProcessPoolExecutor | None = None
        self._size = 0
        self._blob_lock = threading.Lock()
        # the world, its token, its bytes
        self._blob: tuple[World | None, str | None, bytes | None] = (None, None, None)

    def executor(self) -> Workers:
        """The pool and its worker count, created on first use, when it reads
        COUNTRIX_WORKERS."""
        with self._lock:
            if self._executor is None:
                self._size = worker_count()
                self._executor = concurrent.futures.ProcessPoolExecutor(
                    max_workers=self._size, mp_context=multiprocessing.get_context("spawn"))
            return Workers(self._executor, self._size)

    def drop(self) -> None:
        """Shut the pool down; the next board builds a new one, which reads
        COUNTRIX_WORKERS again."""
        with self._lock:
            executor, self._executor, self._size = self._executor, None, 0
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def world_blob(self, world: World) -> tuple[str, bytes]:
        """The world pickled once for a run of tasks: the bytes, and their
        digest as the token the workers cache it under - a server loads a
        fresh world per request, and the same rows keep the workers' copy. The
        world is held here too, so the identity check cannot be fooled by a
        later object at the same address."""
        with self._blob_lock:
            held, token, data = self._blob
            if held is not world or token is None or data is None:
                data = pickle.dumps(world, pickle.HIGHEST_PROTOCOL)
                token = hashlib.sha1(data, usedforsecurity=False).hexdigest()
                self._blob = (world, token, data)
            return token, data


POOL = _Pool()


def available(catalog: list[Strategy] | None = None) -> bool:
    """Whether board() splits its search across workers here. A caller's own
    catalog keeps the solve in this process: a strategy carries compiled
    expressions, which do not pickle, so a worker can only rebuild the playbook
    by reading the files (_Held.playbook) and applying the weights on top."""
    parallel = os.environ.get("COUNTRIX_PARALLEL", "1").lower() not in ("0", "no", "false")
    return parallel and catalog is None and (os.cpu_count() or 1) > 1


def warm(world: World | None = None) -> int:
    """Start the workers now, so the first board does not pay for it: they
    read the playbook, and take a copy of the world when one is given.
    Returns the number started, 0 when the board runs sequentially here - no
    pool, or a worker that could not start, which is written to stderr and
    drops the pool, so boards solve in this process."""
    if not available():
        return 0
    workers = POOL.executor()                 # more tasks than workers, so each gets one
    args = POOL.world_blob(world) if world is not None else (None, None)
    futures = [workers.executor.submit(_prime, *args) for _ in range(workers.size * 3)]
    try:
        for future in futures:
            future.result()
    except Exception as error:  # noqa: BLE001  # any worker failure at startup means solving in this process
        sys.stderr.write("countrix: the solver workers did not start (%s: %s); boards solve in"
                         " this process\n" % (type(error).__name__, error))
        POOL.drop()
        return 0
    return workers.size


def _prime(token: str | None = None, data: bytes | None = None) -> int:
    """In a worker: read the playbook and hold the world, so the first slice
    does not."""
    _HELD.playbook()
    if token is not None and data is not None:
        _HELD.world_of(token, data)
    return os.getpid()


# a playbook folder's stamp: each file's name, modification time and size
Stamp = list[tuple[str, int, int]]


class _Held:
    """A worker's side of the pool: the world it holds between tasks, under
    the token it came with, and the playbook, under its files' stamp. Only
    worker processes read it."""

    def __init__(self) -> None:
        self._world: tuple[str | None, World | None] = (None, None)
        self._playbook: tuple[Stamp | None, list[Strategy] | None] = (None, None)

    def world_of(self, token: str, data: bytes) -> World:
        """The world these bytes pickle, unpickled once per token."""
        held, world = self._world
        if held != token or world is None:
            world = pickle.loads(data)  # nosec B301  # bytes this process pickled for its own workers, never outside input
            self._world = (token, world)
        return world

    def playbook(self) -> list[Strategy]:
        """The playbook, read once per worker and again whenever a file changes."""
        directory = catalog_module.strategies_dir()
        stamp = sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size)
                       for e in os.scandir(directory)
                       if e.name.endswith(".md")) if os.path.isdir(directory) else None
        held, playbook = self._playbook
        if stamp is None or held != stamp or playbook is None:
            playbook = catalog_module.load(directory)
            self._playbook = (stamp, playbook)
        return playbook


_HELD = _Held()


class Verdict(NamedTuple):
    """A candidate as the pool ships it: who is in it, what it scored and how
    it breaks a tie."""
    ids: tuple[int, ...]
    score: float
    tiebreak: float


def _verdict(cand: Candidate) -> Verdict:
    """A candidate as the pool ships it: who is in it, what it scored, how it
    breaks a tie. Everything else is rebuilt where it is needed."""
    return Verdict(ids=tuple(h.id for h in cand.heroes), score=cand.score,
                   tiebreak=cand.tiebreak)


def _revive(world: World, verdict: Verdict) -> Candidate:
    """A verdict as a slim candidate again: its heroes, score and tie-break."""
    cand = Candidate([world.heroes[i] for i in verdict.ids])
    cand.score, cand.tiebreak, cand.raw = verdict.score, verdict.tiebreak, ()
    return cand


class Spec(NamedTuple):
    """The board one worker solves: the seat's draft, from the seat's own
    perspective and its side normalised by board(), and the candidates per
    role."""
    draft: Draft
    pool_size: int


def _solver(world: World, catalog: list[Strategy], spec: Spec) -> Solver:
    """The Solver for a spec's board."""
    seat = spec.draft
    m, red_h, locked_h, bans_h = world.resolve(seat.map_name, seat.red, seat.blue, seat.bans)
    return Solver(world, m, red=red_h, locked=locked_h, banned=bans_h, side=seat.side,
                  catalog=catalog, pool_size=spec.pool_size)


def _worker_solver(token: str, data: bytes, spec: Spec, weights: Mapping[str, float] | None,
                   bounds: Bounds | None = None, standing: Tally | None = None) -> Solver:
    """In a worker: the Solver for a spec's board, on the world the worker
    holds and the playbook under the board's weights - on the scale the
    merged slices froze, when `bounds` is given."""
    solver = _solver(_HELD.world_of(token, data),
                     catalog_module.weighted(_HELD.playbook(), weights), spec)
    if bounds is not None:
        solver.adopt_bounds(bounds, standing)
    return solver


def _bounds(token: str, data: bytes, spec: Spec, weights: Mapping[str, float] | None,
            index: int, count: int) -> Bounds:
    """One slice of the reference sample, in a worker: the low and high it
    sees for each heuristic."""
    return reference_bounds(_worker_solver(token, data, spec, weights), index, count)


def _standing(
        token: str, data: bytes, spec: Spec, weights: Mapping[str, float] | None,
        bounds: Bounds, index: int, count: int) -> Tally:
    """One slice of the reference sample scored under the merged bounds, in a
    worker: each hero's tally in it."""
    return reference_standing(_worker_solver(token, data, spec, weights, bounds), index, count)


def _merge_tallies(tally: Tally, part: Mapping[int, Standing]) -> Tally:
    """Add one slice's per-hero standing into the running tally, in place."""
    for hid, standing in part.items():
        seen = tally.get(hid)
        if seen is None:
            seen = tally[hid] = Standing()
        seen.total += standing.total
        seen.sixes += standing.sixes
    return tally


def _widen(bounds: Bounds, part: Mapping[str, Interval]) -> Bounds:
    """Widen each heuristic's low and high to cover one slice's, in place."""
    for key, got in part.items():
        seen = bounds.get(key)
        bounds[key] = Interval(low=min(got.low, seen.low),
                               high=max(got.high, seen.high)) if seen else got
    return bounds


def _sweep(
        token: str, data: bytes, spec: Spec, weights: Mapping[str, float] | None,
        bounds: Bounds, standing: Tally | None, index: int,
        count: int) -> tuple[int, list[Verdict]]:
    """One slice of one search, in a worker."""
    swept = _worker_solver(token, data, spec, weights, bounds, standing).sweep(index, count)
    return swept.size, [_verdict(c) for c in swept.feasible]


def _rank(
        token: str, data: bytes, spec: Spec, weights: Mapping[str, float] | None,
        bounds: Bounds, standing: Tally | None, verdicts: Iterable[Verdict],
        top: int) -> tuple[list[Verdict], int]:
    """The tail of a split search, in a worker: the merged field ranked and
    refined. -> (the winners, how many candidates refining added)."""
    solver = _worker_solver(token, data, spec, weights, bounds, standing)
    ranked = solver.rank([_revive(solver.world, v) for v in verdicts], top)
    return [_verdict(c) for c in ranked], solver.considered


class Run:
    """One board's pass across the pool: the executor, the world pickled once
    for its tasks, the playbook and weights every search scores under, the
    winners each search keeps, and the board's Watch, which learns of every
    task submitted."""

    def __init__(self, executor: ProcessPoolExecutor, world: World, catalog: list[Strategy],
                 weights: Mapping[str, float] | None, top: int, watch: Watch) -> None:
        self.executor, self.world, self.catalog = executor, world, catalog
        self.weights, self.top, self.watch = weights, top, watch
        self.token, self.data = POOL.world_blob(world)

    def submit[**P, T](
            self, task: Callable[Concatenate[str, bytes, Spec, Mapping[str, float] | None, P], T],
            spec: Spec, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        """Send one task on `spec`'s board to the pool, watched: the task takes
        the world's token and bytes, the spec and the weights, then its own
        arguments."""
        future = self.executor.submit(
            task, self.token, self.data, spec, self.weights, *args, **kwargs)
        self.watch.futures.append(future)
        return future


class Split:
    """One search, split across the pool, a round at a time: the reference
    sample, then the enumeration, then the tail. A caller starts several and
    walks them through the rounds together, so the pool stays full; each
    round first checks that the board has not been superseded. `started` is
    when the search was sent out: its seat's seconds run from there."""

    def __init__(self, run: Run, spec: Spec, slices: int, bounds: Bounds | None = None,
                 standing: Tally | None = None) -> None:
        self.started = time.time()
        self.run, self.spec, self.count = run, spec, slices
        self.bounds, self.standing, self.size = bounds, standing, 0
        self.verdicts: list[Verdict] = []
        self.tallies: list[Future[Tally]] | None = None
        self.scale: list[Future[Bounds]] | None = None if bounds is not None else [
            run.submit(_bounds, spec, i, slices) for i in range(slices)]
        self.slices: list[Future[tuple[int, list[Verdict]]]] | None = None
        self.tail: Future[tuple[list[Verdict], int]] | None = None

    def _scale(self) -> Bounds:
        """The bounds the search runs under: set once rank_roster() has run."""
        if self.bounds is None:
            raise RuntimeError("the split has no scale before rank_roster()")
        return self.bounds

    def rank_roster(self) -> None:
        """Take the scale the slices drew, and send the sample out again to be
        scored under it: each hero's standing, which ranks the pools."""
        self.run.watch.check()
        if self.scale is not None:
            self.bounds = {}
            for future in self.scale:
                _widen(self.bounds, future.result())
            self.scale = None
        if self.standing is None and self.tallies is None:
            self.tallies = [self.run.submit(_standing, self.spec, self._scale(), i, self.count)
                            for i in range(self.count)]

    def sweep(self) -> None:
        """Take the standing, and send the enumeration out."""
        self.rank_roster()
        if self.tallies is not None:
            self.standing = {}
            for future in self.tallies:
                _merge_tallies(self.standing, future.result())
            self.tallies = None
        self.slices = [
            self.run.submit(_sweep, self.spec, self._scale(), self.standing, i, self.count)
            for i in range(self.count)]

    def merge(self) -> None:
        """Collect the slices and send the merged field off to be ranked."""
        self.run.watch.check()
        if self.slices is None:
            raise RuntimeError("merge() follows sweep()")
        self.verdicts = []
        for future in self.slices:
            self.size, part = future.result()
            self.verdicts.extend(part)
        self.tail = self.run.submit(_rank, self.spec, self._scale(), self.standing,
                                    self.verdicts, self.run.top)

    def _scaled_solver(self) -> Solver:
        """The Solver for this split's board, on the scale its slices froze."""
        solver = _solver(self.run.world, self.run.catalog, self.spec)
        solver.adopt_bounds(self._scale(), self.standing)
        return solver

    def solved(self) -> Solved:
        """The Solved that Solver.solve() would have returned."""
        self.run.watch.check()
        if self.tail is None:
            raise RuntimeError("solved() follows merge()")
        winners, refined = self.tail.result()
        solver = self._scaled_solver()
        solver.considered = self.size + refined
        return Solved(solver, [solver.hydrate(_revive(self.run.world, v)) for v in winners])

    def swept(self) -> Swept:
        """The Swept of the whole field, as one Solver.sweep() would have left
        it: what a six is ranked against."""
        self.run.watch.check()
        return Swept(self._scaled_solver(), self.size,
                     [_revive(self.run.world, v) for v in self.verdicts])


class NullSplit:
    """A search not split: each round only checks that the board has not
    been superseded, and solved() and swept() are None, so the seat searches
    for itself in this process, timing its own search."""
    bounds: Bounds | None = None
    standing: Tally | None = None
    started: float | None = None

    def __init__(self, watch: Watch) -> None:
        self.watch = watch

    def rank_roster(self) -> None:
        """The seat's own search draws its scale: only the check."""
        self.watch.check()

    def sweep(self) -> None:
        """Nothing to send out: only the check."""
        self.watch.check()

    def merge(self) -> None:
        """Nothing to collect: only the check."""
        self.watch.check()

    def solved(self) -> Solved | None:
        """None, after the check: the seat searches for itself."""
        self.watch.check()
        return None

    def swept(self) -> Swept | None:
        """None, after the check: the seat sweeps its own field."""
        self.watch.check()
        return None
