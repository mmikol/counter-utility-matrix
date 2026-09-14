# Backlog

What is worth doing next, why, and what it would cost - kept by the
maintainer skill: a run marks an item done with its commit, adds what a
check or a lesson suggests, and drops what no longer applies. Items are
ordered by payoff over blast radius; the first is the one to pick up.

## In progress

- **Run a board's independent solves in parallel** - `multithreading` branch.
  Blue's optimal and red's counter in two spawned workers, the fill in the
  parent, the pessimistic case after. A click halves on a machine with
  spare cores (2.1 s to 1.1 s here); the answer is the sequential one.
  Passes three ways (the local suite went from 4.5 to 1.7 minutes, the
  image's from 5.6 to 2.2); the inference container peaks at 410 MiB of
  its 1 GiB, the data container got 2 GiB for the suite. Done when the
  branch is merged.

## Next

- **Memoize the per-hero parts of the metrics.** Thousands of candidate
  sixes share the same heroes; `compute.team_metrics` rebuilds each hero's
  pool, kit sums and keyword sets for every candidate. 70% of a solve is
  preparing about 15,500 candidates. Cheaper than any parallelism and
  compounds with it. Cost: a day; risk: none to the answer if the memo is
  keyed on the hero and the map.
- **Split candidate scoring across the workers inside one solve.** After
  the memo. The world and the catalog have to reach the workers (the world
  pickles in 6 ms; the catalog's compiled expressions do not, so workers
  load it from the files). Cost: two days; risk: moderate, the reference
  sample and the refine step must stay identical.
- **A pool of pre-loaded workers in the inference service.** The servers
  accept requests concurrently but share one GIL, so two people clicking
  at once queue up. Matters the day a team uses the board together. Cost:
  a day once the per-board pool exists; risk: memory per worker.
- **Fetch the sources concurrently, one polite pace per host.** Blizzard,
  the wiki and the counter site can be pulled at the same time while each
  keeps its delay; the database writes keep their order (heroes before
  kits). Only the first build and the weekly full refresh get faster.
  Cost: a day; risk: the politeness must stay per host, not per thread.
- **Run the test suite in parallel.** A worker plugin would take the
  local run from four and a half minutes to under two. The database-bound
  tests share one cluster and mostly read; the cache-driven pulls roll
  back. Cost: an hour; risk: a test that assumed it ran alone.
- **Reconsider the pool cap.** The tools allow a pool of 12; a pool of 8
  with no locks needs more than 1 GiB and would be killed inside the
  container. Either lower the cap to what the container can hold or size
  the container for it. Cost: an hour.

## Done

- **A deterministic solver** - `bf91ef8`. Style ties broke by set order,
  so the process's hash seed could change the answer; ties break by name.
- **A 75% coverage bar and ruff at 100 columns** - `bf91ef8`.
- **Announced heroes end to end** - `382ac1a`.
