# Backlog

What is worth doing next, why, and what it would cost. Ordered by payoff
over blast radius; the first is the one to pick up. The maintainer skill
keeps it current.

## Next

- **Tunings by map.** The user's request: each map carries its own tuning
  set - a weight per heuristic (and a params dial where a rule has one)
  that applies when that map is on the board, so a rule can matter on
  King's Row and whisper on Ilios. Stored in the database, not the files:
  a `map_tunings` table (map, strategy, weight, params, reason, stamped)
  the `tune` tool writes when the call names a map, mirrored in the
  strategies export; the catalog applies the map's set over the file's
  defaults when the solver is built for that map (`catalog.weighted`
  already layers a session's slider values the same way, so the map's set
  is one more layer under the sliders); the playbook tab shows the map's
  values when a map is chosen and the file's when none is, and the board
  result names which set it was scored under. Cost: two days - a
  migration, the tool's `map` argument, the layering, the tab, the facts
  line that names the set - and a test that the same six scores
  differently under two maps' sets.
- **The fact engine's dependent variables.** The equation is stated per
  domain (a selection's own row, then its joins) and the math page says
  so; the joins the data can still yield are listed under "Fact engine"
  below, best first.
- **Voice control for the picks.** Say "blue Ana", "red Pharah", "swap
  Ana for Kiriko", "clear red" and the board sets the picks, no clicking
  - for a draft called out at the table. The browser's speech
  recognition (`SpeechRecognition`, Chrome and Safari; no key, no
  service) hears a phrase, a small grammar maps it to the board's own
  toggle calls with hero names matched the way the roster spells them
  (Lúcio, Soldier: 76, D.Va, Wrecking Ball), a mis-hear is refused with
  the flash the board already has, and a badge shows the microphone is
  live; off by default, a button in the header turns it on. Cost: a day,
  half of it the name matching; nothing leaves the browser.
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
- **Re-prove the real-World gate's boards, banned boards included.** In
  CI the search is gated by an enumeration of six synthetic boards
  (`test_the_search_reaches_the_enumerated_maximum`, two bans on one of
  them). `tests/fixtures/optimal.json` is live again: its 24 boards were
  enumerated under the shipped playbook and the default engine, whose
  score splits into a term per hero and one per pair, so every legal six
  of a board scores in seconds; the fixture stamps both, and any change to
  either - a new assumption file included, since the digest covers every
  strategy file - fails the gate until the boards are enumerated again.
  `scripts/optimal.py` still holds out every board with bans
  (`OPTIMAL_STALE_BANNED`, on by default), so the gate proves nothing
  about the real roster under bans. The work: enumerate a set with one to
  five bans among the shapes; and, once the playbook scores, under the
  reference playbook `tests/fixtures/playbook` (`COUNTRIX_STRATEGIES`
  selects it), whose heuristics do not split per hero, so that
  enumeration is hours offline again. A tune of the live playbook never
  stales that set. The gate test then solves with
  `catalog=catalog.load(FIXTURE_PLAYBOOK)` and compares the stamp with
  that playbook's digest; `OPTIMAL_STALE_BANNED` and `read_proofs`'
  `stale_banned` filter go, and `test_the_proven_boards_cover_every_input`
  trades its no-bans assert for a bans clause. Cost: minutes for the
  banned boards under the engine alone, the enumeration's hours for the
  reference playbook, an hour in the repo.
- **Weights that learn on their own.** The user wants them to, with the
  sliders as the manual override. The weights were fitted once to a
  benchmark of community comps; nothing refits them. The owner's played
  maps are recorded now (`record_match`, migration 024), each stamped with
  the playbook's digest, and `validate_playbook` judges the playbook
  against them without moving a weight. A fit from them waits on the
  guard's sample - 191 decided maps for an even map won 60% of the time -
  and a refitted playbook is a new digest, judged only on the maps played
  after it. Until then the signal the data holds: fit the weights so that
  the solver's per-hero contribution ranks agree with each hero's
  published win rate on the map, capped per step, every change a
  tuning-log line with "fit" as its reason. The default engine's three
  weights (`inference/base.py`) are calibrated defaults, not a fit: the
  same recorded maps are to refit them. Cost: a day.
- **Memoize the per-hero parts of the metrics.** `team.team_metrics`
  rebuilds each hero's pool, kit sums and keyword sets for every
  candidate and is ~41% of a sequential board. A per-world term table
  measured 3x on the function, ~5% on a board. Cost: a day; risk: none to
  the answer if the memo is keyed on the hero and the map.
- **What the scrub left in the data layer.** Domina's weapon publishes no
  rate (dps 0); conditional cooldowns are mis-split for some abilities;
  the match-up reader gives no verdict on about two in three written
  wiki cells, and seven hero articles have no written cell. Cost: two
  days.
- **Facts no metric reads.** `ability_modifiers` holds speed, damage-taken
  and healing-received buffs; no metric in
  `facts/team.py` or `facts/compute.py` reads `hero.modifiers`. Knockbacks as their own
  count (Control's edges), damage beams apart from healing beams, area
  healing apart from area damage. Cost: a day each.
- **Off-shapes never win.** 2-1-3 and 2-3-1 land within 2-8 percent of the
  best 2-2-2 and the benchmark endorses three-support holds and
  three-damage attacks (57-79 percent of the optimal today). The shape
  rules are scored constraints, which the fit does not touch. Cost: a day
  to fit their dials to the benchmark's off-shape entries.
- **One hero on most boards.** D.Mon is in most optimal sixes on the
  strength of the roster's highest win rate. A win rate on a low pick
  rate is a specialist's: weigh it by its sample.
- **Shard the local search by seed.** The countered case's refine is the
  last serial block (~0.12 s). The result set holds; the reported
  `considered` count depends on seed order and would change.
- **A strict dead-CSS test.** The test word-matches class names, so a dead
  compound selector passes (`.hcard .legend` did). Needs an exception list
  for the four classes built by concatenation.
- **Fetch the sources concurrently, one polite pace per host.** Blizzard
  and the wiki can be pulled at the same time while each keeps its delay; the database writes keep their order (heroes before
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

About half the fact kinds on a full board are independent (one hero, one
map, the meta, the bans); the rest are intersections (hero x map, hero x
enemy, hero x ally, the team, the matchup). What the data can still
yield, best first:

- **Refuse a second heuristic on an aliased metric.** Several keys are
  one measure under two names - every `matchup.*_diff` normalises exactly
  like its blue half because red is constant across a board's sample,
  `safe_count` is 6 minus `exposed_count`, `heal_ratio` is
  `heal_peak_supports` over a constant - so the catalog should refuse a
  second heuristic on an alias of a metric already in use. Two tags are
  still loose: `team.deployables` counts Reinhardt's, Sigma's and
  Ramattra's barriers and Mei's wall; `team.hitscan` counts support and
  tank guns. Cost: half a day for the alias table and the catalog check,
  half a day for the tags.
- **Tag every fact independent or dependent.** Each fact kind names the
  tables it joins (none for an independent one); the facts tab shows the
  tag and the board's counts by kind, so the equation's two terms are
  visible per board. Cost: half a day.
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
  plus a constant in `facts/compute.py` of which tool beats which.
  Cost: two days, half of it the constant.
- **History across captures.** Every rates pull appends a snapshot; only the last step
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
  rush as a style and speed boost (Lúcio, Juno); peel as its own tool
  set; main-tank and main-healer tags; per-role splits (a support line's
  damage, a tank pair's synergy, mobility per role); negative synergies
  (pairs that clash); healing and defensive ultimates as sustain (only
  damage ultimates carry a figure); projectile-eating tools (Defense
  Matrix, Kinetic Grasp) and hack against deployables; damage mitigation;
  a hero's win-rate variance across maps (generalist or specialist); ult
  charge lost on a swap. Each is a metric in `facts/compute.py` first,
  then a rule. Cost: an hour to a day each; the per-role splits are the
  cheapest and unlock the most.

What the sources do not publish, so no fact can: per-map rates by rank,
per-side rates, per-stage rates, and a strength for a counter beyond the
few match-ups the wiki rates (the counters table is a list).

## Done

- **The playbook is judged against the recorded matches** - `match-level`
  branch. `validate_playbook` and `python -m ui.validation` rescore each
  map with evaluate from both seats, score five models out of sample on a
  time and a sessions split with bootstrap intervals over sessions, ablate
  each strategy family, judge a playbook only from its digest's first map,
  and withhold the verdict below (5.6 / b)^2 decided maps. Pure Python;
  the page is personal use, in `db/raw`.
- **The owner's matches are the second user input** - `match-level`
  branch. Migration 024 adds `matches` and `match_picks`, one row a map
  with both sixes, the bans, blue's side and blue's result, under the
  `user` source. The door's `record_match` checks a map as the board
  checks a board and as only a played map can be, and stamps the
  playbook's digest; `list_matches` and `delete_match` read and fix the
  record; the board's record tab and the `/record` skill call it;
  `facts/matches.py` reads it back as `Match` records; `db_rebuild` keeps
  it across the drop.
- **The strategies are the one user input** - `data-only-inputs` branch.
  `seasons` and `synergies` are pulled from the wiki (`pull_seasons`,
  `pull_synergies`); `map_playstyle` and `comp_archetypes` are dropped
  (migration 018): a map's styles are derived at load from the per-map
  rates and the wiki's hero playstyles, the expected shape is
  `compute.EXPECTED_SHAPE`. The authored CSVs are deleted and
  `load_authored` mirrors the strategy files only. The daily refresh
  pulls the seasons, so a snapshot is stamped with the season live that
  day. The scraped counter site is gone (migration 019): `pull_counters`
  reads the Match-Up cells of every hero's wiki article into `counters`,
  `map_strategy` is dropped and a hero's best maps are derived at load
  from Blizzard's per-map rates, the second rates population and its
  snapshots are deleted. The sources are Blizzard's site and the wiki.
- **Facts audited, strategies weighed against them, weights fitted** -
  `facts-and-weights` branch. Hero numbers rebuilt from the kit rows
  (keywords, three kit sets, units), 238 strategies
  reviewed against the database with 102 fixed, weights fitted to 117
  community comps (held-out AUC 0.79 -> 0.86), a second scrub of 71
  findings applied. Never-picked heroes 19 -> 9 of 53.
- **Every search split across a worker pool** - `scrub` branch. Static
  guards evaluated once per solver, shared guards once per candidate,
  sections as attribute lookups; the reference sample and the enumeration
  sliced across `max(6, min(cores, 12))` spawned workers, verdicts only
  crossing. A board 1.6-2.1 s -> 0.3-0.5 s, sequential 1.7x, answers
  byte-identical.
- **The community's rules are the playbook** - `community-playbook`
  branch. Three hundred mined from reddit (r/OverwatchUniversity,
  r/Competitiveoverwatch, r/Overwatch: 172 threads and 11,800 comments
  through reddit) by twelve analysts over two
  passes, standardized, stored through the validated add, checked on six
  boards and their reference samples; then five reviewers read them
  against each other and 62 went as duplicates behind aliased metrics or
  cancelling pairs, ten guards and dials were retuned and five bodies
  rewritten: 238 rules and the user's five assumptions, a citation for
  every one in `inference/README.md`. The user's hand-built rules were
  removed on their word; the queue's two-tank cap returned as a quoted
  rule. Under 300 rules a board peaked at 1.8 GB and died in its 1 GiB
  container: the solver now scores every candidate slim (score and
  tie-break only) and hydrates the winners' breakdowns, so a board peaks
  at 150 MB and solves in about 5 seconds instead of 1.5 - the
  memoization item above is the rest of the way back.
- **Maintenance, end to end** - `maintain` branch. Five parallel passes
  (the three layers, the docs and skills, the root and infrastructure):
  dead code, dead styling and stale comments out, the docs shorter and
  true, each container mounting only what it reads, the gitignore cut to
  what the tree produces, tests that could not fail replaced by pins;
  then the older migrations' comments rewritten as history, the board's
  last helper text removed, the launch configs named for the project,
  and `--cov` defined once in pyproject.
- **The look is the game's again** - `fe32e70`. Dark surfaces, Bebas
  Neue, a gold accent, red and blue for the sides.
- **Six debts cleared** - `debt` branch. The suite shares the most-read
  board (three minutes to two locally, four to three in the image); red's likely comp is a
  `Result` like every seat; the fixture playbook is the nineteen rules
  the tests use; the script trusts the engine's unscored reason; the
  math page is `ui/static/math.html`; the board script is three files
  (comps, playbook, board). Found on the way: the derive prompt anchored
  its style on rule ids the playbook no longer holds - it now falls back
  to one file per form.
- **Red's likely picks from the map and the meta** - `team-headers`
  branch. `compute.expected_picks`: their revealed picks, then the
  most-picked heroes on the map, within the queue's two-tank limit; the
  comps tab's right seat.
- **A heuristic's weight stores into its file from the board** - `f131f80`.
- **A heuristic's weight is a slider under its card** - `2156473`. Only
  heuristics have one; 1 to 10 to the hundredth with a number box for the
  exact figure; the file's weight is the inferred default and a reset; a
  setting rides with the board request (`weights=id:value`, `weights` on
  the `board` tool) and never touches the file.
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
