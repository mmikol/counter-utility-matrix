# Backlog

What is worth doing next, why, and what it would cost - kept by the
maintainer skill: a run marks an item done with its commit, adds what a
check or a lesson suggests, and drops what no longer applies. Items are
ordered by payoff over blast radius; the first is the one to pick up.

## In progress

Nothing - main holds everything and every feature branch is deleted; the
next feature opens its own branch.

## Next

- **The fact engine's dependent variables.** The equation is stated per
  domain (a selection's own row, then its joins) and the math page says
  so; the joins the data can still yield are listed under "Fact engine"
  below, best first - the pairwise numbers, blue pick against red pick,
  are the one to start with.
- **Trim the shipped playbook's prose to three sentences.** The user's
  rule for every strategy; the from-scratch three follow it and the
  add tool enforces it, but the 38 shipped files still run long. Cost:
  an hour, if the shipped playbook is kept at all.
- **Weights that learn on their own.** The user wants them to, with the
  sliders as the manual override. Learning needs a signal, and the one
  it had - recorded comps with a win or loss - was removed on the user's
  word. Two ways back, to decide with the user: (a) a minimal outcome
  record, one row per board with won or lost and the weights in force,
  and a `fit` that nudges each heuristic's weight toward the
  contributions that won (a logistic fit over the contribution vectors,
  capped per step, every change a tuning-log line with "fit" as its
  reason); or (b) no recording: fit the weights so that the solver's
  per-hero contribution ranks agree with each hero's published win rate
  on the map, a weaker signal that the data already holds. Cost: (a) two
  days including the record and its tool; (b) a day.

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

- **Tag every fact independent or dependent.** Each fact kind names the
  tables it joins (none for an independent one); the facts tab shows the
  tag and the board's counts by kind, so the equation's two terms are
  visible per board. Cost: half a day; 127 kinds to classify once.
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

- **A heuristic's weight stores into its file from the board** - `f131f80`.
- **A heuristic's weight is a slider under its card** - `2156473`.
  Only heuristics have one; 1 to 10 to the hundredth with a number box for
  the exact figure; the file's weight is the inferred default and a reset;
  a setting rides with the board request (`weight=id:value`, `weights` on
  the `board` tool) and never touches the file; every result names the
  weights it was scored under.
- **Unscored, never 100 / 100** - `0c10dd7`. A playbook with no scoring
  term ties every legal six at zero; the board now says so. The
  from-scratch playbook holds its three rules and scores.
- **The roster holds to the playbook's shape limits** - `d1b0718`.
- **Run a board's independent solves in parallel** - `5baaa95`. Blue's
  optimal and red's counter in two spawned workers, the fill in the
  parent, the pessimistic case after; a click halves on a machine with
  spare cores (2.1 s to 1.1 s), the answer is the sequential one.
- **A deterministic solver** - `bf91ef8`. Style ties broke by set order,
  so the process's hash seed could change the answer; ties break by name.
- **A 75% coverage bar and ruff at 100 columns** - `bf91ef8`.
- **Announced heroes end to end** - `382ac1a`.
