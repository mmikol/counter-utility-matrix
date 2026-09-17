# Backlog

What is worth doing next, why, and what it would cost - kept by the
maintainer skill: a run marks an item done with its commit, adds what a
check or a lesson suggests, and drops what no longer applies. Items are
ordered by payoff over blast radius; the first is the one to pick up.

## In progress

Nothing - main holds everything and every feature branch is deleted; the
next feature opens its own branch.

## Next

- **Tunings by map.** The user's request: each map carries its own tuning
  set - a weight per heuristic (and a params dial where a rule has one)
  that applies when that map is on the board, so a rule can matter on
  King's Row and whisper on Ilios. Stored in the database, not the files:
  a `map_tunings` table (map, strategy, weight, params, reason, stamped)
  the `tune` tool writes when the call names a map, mirrored in the
  strategies export; the catalog applies the map's set over the file's
  defaults when the solver is built for that map (`catalog.weighted`
  already layers a session's slider values the same way, so the map's
  set is one more layer under the sliders); the playbook tab shows the
  map's values when a map is chosen and the file's when none is, and the
  board result names which set it was scored under. Cost: two days - a
  migration, the tool's `map` argument, the layering, the tab, the
  facts line that names the set - and a test that the same six scores
  differently under two maps' sets.
- **The fact engine's dependent variables.** The equation is stated per
  domain (a selection's own row, then its joins) and the math page says
  so; the joins the data can still yield are listed under "Fact engine"
  below, best first - the pairwise numbers, blue pick against red pick,
  are the one to start with.
- **Voice control for the picks.** Say "blue Ana", "red Pharah", "swap
  Ana for Kiriko", "clear red" and the board sets the picks, no clicking
  - for a draft called out at the table. The browser's speech
  recognition (`SpeechRecognition`, Chrome and Safari; no key, no
  service) hears a phrase, a small grammar maps it to the board's own
  toggle calls with hero names matched the way the roster spells them
  (Lúcio, Soldier: 76, D.Va, Wrecking Ball), a mis-hear is refused with
  the flash the board already has, and a badge shows the microphone is
  live; off by default, a button in the header turns it on. Cost: a
  day, half of it the name matching; nothing leaves the browser.
- **Simulation and mathematical proving.** Two ways to check what the
  score claims. (a) A fight simulation from the kits' own numbers -
  damage and healing per second, pools, ranges, cooldowns - that plays a
  six against a six for a few seconds of engagement and says who is
  standing, so a comp's score can be set against a modelled fight rather
  than trusted; deterministic, seeded where it must draw. (b) Proofs of
  the solver's properties, as tests where they can be and as derivations
  on the math page where they cannot: the same board gives the same six;
  scaling every weight by one factor leaves the argmax unchanged; a
  normalised term stays within 0..1 and the reference sample bounds it;
  fight odds split 100 exactly; the local search never lowers the score.
  Cost: (a) three to four days, the kit model most of it; (b) a day for
  the tests, a day for the page.
- **Weights that learn on their own.** The user wants them to, with the
  sliders as the manual override. Learning needs a signal, and the one it
  had - recorded comps with a win or loss - was removed on the user's
  word. Two ways back, to decide with the user: (a) a minimal outcome
  record, one row per board with won or lost and the weights in force,
  and a `fit` that nudges each heuristic's weight toward the
  contributions that won (a logistic fit over the contribution vectors,
  capped per step, every change a tuning-log line with "fit" as its
  reason); or (b) no recording: fit the weights so that the solver's
  per-hero contribution ranks agree with each hero's published win rate
  on the map, a weaker signal the data already holds. Cost: (a) two days
  including the record and its tool; (b) a day.
- **Memoize the per-hero parts of the metrics.** Thousands of candidate
  sixes share the same heroes; `compute.team_metrics` rebuilds each
  hero's pool, kit sums and keyword sets for every candidate, and that
  preparation is most of a solve now that scoring is slim. Cheaper than
  any parallelism and compounds with it. Cost: a day; risk: none to the
  answer if the memo is keyed on the hero and the map.
- **Split candidate scoring across the workers inside one solve.** After
  the memo. The world and the catalog have to reach the workers (the
  world pickles in 6 ms; the catalog's compiled expressions do not, so
  workers load it from the files). Cost: two days; risk: moderate, the
  reference sample and the refine step must stay identical.
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
  local run from a little over two minutes to under one. The
  database-bound tests share one cluster and mostly read; the
  cache-driven pulls roll back. Cost: an hour; risk: a test that assumed
  it ran alone.
- **Reconsider the pool cap.** The tools allow a pool of 12; a pool of 8
  with no locks needs more than 1 GiB and would be killed inside the
  container. Either lower the cap to what the container can hold or size
  the container for it. Cost: an hour.

## Fact engine: more dependent variables

The facts today: 127 kinds on a full board - about 60 independent (one
hero, one map, the meta, the bans), the rest intersections (hero x map,
hero x enemy, hero x ally, the team, the matchup). What the data can
still yield, best first:

- **Mend the tags the playbook review found.** Five reviewers reading
  244 rules against the kit data found the vocabulary misleading in
  places, and every rule on those keys inherits it: `team.range_max`
  takes the largest range on any ability or ultimate, so Cassidy reads
  200 m, Orisa 180 and Widowmaker 20 - the weapon's range is the number a
  sniper rule means; `team.flyers` tags D.Va, Sigma, Mercy, Juno and
  Illari, so a flier guard is always on; `team.deployables` counts
  Reinhardt's, Sigma's and Ramattra's barriers and Mei's wall but not
  Torbjörn's turret or Illari's pylon; `team.invuln` is mostly escape
  tools while Immortality Field and Sound Barrier are untagged;
  `team.barrier_hp` includes ultimates (Symmetra 4,000); `team.hitscan`
  counts support and tank guns. And several keys are one measure under
  two names - every `matchup.*_diff` normalises exactly like its blue
  half because red is constant across a board's sample, `safe_count` is
  6 minus `exposed_count`, `exposure_share` is `exposed_count` over 6,
  `heal_ratio` is `heal_peak_supports` over a constant - so the catalog
  should refuse a second heuristic on an alias of a metric already in
  use. Cost: a day for the tags (a weapon-range key, a turret and pylon
  tag, a true invulnerability tag, a flier tag from flight only), half a
  day for the alias table and the catalog check.
- **Tag every fact independent or dependent.** Each fact kind names the
  tables it joins (none for an independent one); the facts tab shows the
  tag and the board's counts by kind, so the equation's two terms are
  visible per board. Cost: half a day; 127 kinds to classify once.
- **Pairwise numbers, blue pick against red pick.** One-shot: whose
  biggest hit meets whose pool. Time to kill: pool over damage floor,
  each way. Out-range: whose longest reach exceeds whose. All from
  numbers the hero facts already carry; today they exist only summed per
  team. Cost: a day; the matrix is 36 pairs at most.
- **Tool against tool, per pair.** Anti-heal against a healer, a piercer
  against a barrier holder, hitscan against a flyer, crowd control
  against an engage tool, an invulnerability against a damage ultimate, a
  cleanse against a debuff. The team-level "wars" exist; the per-pair
  version names who answers whom and with what, from the kit keywords
  plus a small authored table of which tool beats which. Cost: two days,
  half of it the table.
- **History across captures.** Seven snapshots exist; only the last step
  is a fact. A hero's win-rate series, who is rising and falling this
  season, and the patch each change followed. Cost: a day.
- **Gaps named, not counted.** Coverage says "answers 2/3 red picks";
  name the unanswered pick, the pick nobody protects, the enemy nobody
  out-ranges. Cost: an hour each.
- **Side-specific team facts.** On attack, the engage tools and anti-heal
  the team brings; on defense, its deployables and barriers. A side
  constraint would read these; a fact should state them. Cost: an hour.

- **What the community says and no metric measures.** Building the
  community playbook left these unexpressed, each said by several voices:
  a rush archetype and speed boost (Lúcio, Juno); peel as its own tool
  set; main-tank and main-healer tags; per-role splits (a support line's
  damage, a tank pair's synergy, mobility per role); negative synergies
  (pairs that clash); healing and defensive ultimates as sustain (only
  damage ultimates carry a figure); projectile-eating tools (Defense
  Matrix, Kinetic Grasp) and hack against deployables; damage mitigation;
  a hero's win-rate variance across maps (generalist or specialist); ult
  charge lost on a swap. Each is a metric in `ui/facts/compute.py` first,
  then a rule. Cost: an hour to a day each; the per-role splits are the
  cheapest and unlock the most.

What the sources do not publish, so no fact can: per-map rates by rank,
per-side rates, per-stage rates, and a strength for a counter (the
counters table is a list).

## Done

- **The community's rules are the playbook** - `community-playbook`
  branch. Three hundred mined from reddit (r/OverwatchUniversity,
  r/Competitiveoverwatch, r/Overwatch: 172 threads and 11,800 comments
  through the feeds and the archive's search) by twelve analysts over two
  passes, standardized, stored through the validated add, checked on six
  boards and their reference samples; then five reviewers read them
  against each other and 62 went as duplicates behind aliased metrics or
  cancelling pairs, ten guards and dials were retuned and five bodies
  rewritten: 238 rules and the user's five assumptions, a citation for
  every one in `inference/README.md`. The user's five hand-built rules
  were removed on their word; the queue's two-tank cap returned as a
  quoted rule. Under 300 rules a board peaked at 1.8 GB and
  died in its 1 GiB container: the solver now scores every candidate
  slim (score and tie-break only) and hydrates the winners' breakdowns,
  so a board peaks at 150 MB and solves in about 5 seconds instead of
  1.5 - the memoization item below is the rest of the way back.
- **Maintenance, end to end** - `maintain` branch. Five parallel passes
  (the three layers, the docs and skills, the root and infrastructure):
  dead code, dead styling and stale comments out, the docs shorter and
  true, each container mounting only what it reads, the gitignore cut to
  what the tree produces, tests that could not fail replaced by pins;
  then the older migrations' comments rewritten as history, the board's
  last helper text removed, the launch configs named for the project,
  and `--cov` defined once in pyproject.
- **Never five supports** - `b00aafd`. The playbook's second hard limit,
  `require: team.supports <= 4`; the roster refuses the fifth.
- **The look is the game's again** - `fe32e70`. Dark surfaces, Bebas
  Neue, a gold accent, red and blue for the sides.
- **Six debts cleared** - `debt` branch. The suite reads the map notes
  off one solved board and shares the most-read board (three minutes to
  two locally, four to three in the image); red's likely comp is a
  `Result` like every seat; the fixture playbook is the nineteen rules
  the tests use; the script trusts the engine's unscored reason; the
  math page is `ui/static/math.html`; the board script is three files
  (comps, playbook, board). Found on the way: the derive prompt anchored
  its style on rule ids the playbook no longer holds - it now falls back
  to one file per form.
- **The playbook is the user's own rules** - `team-headers` branch.
  `inference/strategies/` holds the rules built one at a time (the
  two-tank limit, hitscan cover against fliers, the counters with a
  grain of salt, optimal play); the 38-rule playbook it replaced is the
  tests' reference at `tests/fixtures/playbook/`, and no experiment
  ships.
- **Red's likely picks from the map and the meta** - `team-headers`
  branch. `compute.expected_picks`: their revealed picks, then the
  most-picked heroes on the map, within the queue's two-tank limit; the
  comps tab's right seat.
- **A heuristic's weight stores into its file from the board** - `f131f80`.
- **A heuristic's weight is a slider under its card** - `2156473`. Only
  heuristics have one; 1 to 10 to the hundredth with a number box for the
  exact figure; the file's weight is the inferred default and a reset; a
  setting rides with the board request (`weight=id:value`, `weights` on
  the `board` tool) and never touches the file; every result names the
  weights it was scored under.
- **Unscored, never 100 / 100** - `0c10dd7`. A playbook with no scoring
  term ties every legal six at zero; the board now says so.
- **The roster holds to the playbook's shape limits** - `d1b0718`.
- **Run a board's independent solves in parallel** - `5baaa95`. Blue's
  optimal and red's counter in two spawned workers, the fill in the
  parent, the pessimistic case after; a click halves on a machine with
  spare cores (2.1 s to 1.1 s), the answer is the sequential one.
- **A deterministic solver** - `bf91ef8`. Style ties broke by set order,
  so the process's hash seed could change the answer; ties break by name.
- **A 75% coverage bar and ruff at 100 columns** - `bf91ef8`.
- **Announced heroes end to end** - `382ac1a`.
