# Backlog

What is worth doing next, why, and what it would cost - kept by the
maintainer skill: a run marks an item done with its commit, adds what a
check or a lesson suggests, and drops what no longer applies. Items are
ordered by payoff over blast radius; the first is the one to pick up.

## In progress

- **The fact engine's dependent variables** - `fact-engine` branch. The
  equation now says what the engine does: FACTS = INDEPENDENT ∪ DEPENDENT,
  each selection alone read from one table, then the joins across the
  selections (hero ⋈ map, hero ⋈ enemy, hero ⋈ ally, the team, the
  matchup, the bans). The math page, the docs and the skills state it
  that way. Next is the list under "Fact engine" below, best first. Done
  when the pairwise numbers are facts and the branch is merged.

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

## Fact engine: more dependent variables

The facts today: 127 kinds on a full board - about 60 independent (one
hero, one map, the meta, the bans), the rest intersections (hero x map,
hero x enemy, hero x ally, the team, the matchup). What the data can still
yield, best first:

- **Pairwise numbers, blue pick against red pick.** One-shot: whose
  biggest hit meets whose pool. Time to kill: pool over damage floor, each
  way. Out-range: whose longest reach exceeds whose. All from numbers the
  hero facts already carry; today they exist only summed per team. Cost:
  a day; the matrix is 36 pairs at most.
- **Tool against tool, per pair.** Anti-heal against a healer, a piercer
  against a barrier holder, hitscan against a flyer, crowd control against
  an engage tool, an invulnerability against a damage ultimate, a cleanse
  against a debuff. The team-level "wars" exist; the per-pair version
  names who answers whom and with what, from the kit keywords plus a small
  authored table of which tool beats which. Cost: two days, half of it the
  table.
- **The map's expected opposition.** The most-picked heroes on this map
  (the leaders fact ranks by win rate), and the picks red is likely to add
  given what it has. Cost: half a day.
- **History across captures.** Seven snapshots exist; only the last step
  is a fact. A hero's win-rate series, who is rising and falling this
  season, and the patch each change followed. Cost: a day.
- **Gaps named, not counted.** Coverage says "answers 2/3 red picks";
  name the unanswered pick, the pick nobody protects, the enemy nobody
  out-ranges. Cost: an hour each.
- **Side-specific team facts.** On attack, the engage tools and anti-heal
  the team brings; on defense, its deployables and barriers. The side
  constraints read these; a fact should state them. Cost: an hour.

What the sources do not publish, so no fact can: per-map rates by rank,
per-side rates, per-stage rates, and a strength for a counter (the
counters table is a list).

## Done

- **Run a board's independent solves in parallel** - `5baaa95`. Blue's
  optimal and red's counter in two spawned workers, the fill in the
  parent, the pessimistic case after; a click halves on a machine with
  spare cores (2.1 s to 1.1 s), the answer is the sequential one.
- **A deterministic solver** - `bf91ef8`. Style ties broke by set order,
  so the process's hash seed could change the answer; ties break by name.
- **A 75% coverage bar and ruff at 100 columns** - `bf91ef8`.
- **Announced heroes end to end** - `382ac1a`.
