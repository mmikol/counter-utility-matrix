# The INFERENCE LAYER - `inference/`

Facts in, the optimal composition out. The layer owns the right-hand
side of the equation in [architecture.md](architecture.md):

```
STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS   the playbook: markdown files in strategies/
COMP       = ARGMAX[ STRATEGIES( FACTS ) ]  the solver searches; the agent argues
```

Two things infer:

- **The solver**: deterministic arithmetic. It reads the strategy files'
  frontmatter, scores every candidate six with the facts layer's metrics,
  and returns the best. No model, no API, and no randomness but seeded
  draws: the reference sample and the refine's restarts. It cannot read
  prose.
- **The agent**: a Claude Code session on the `/comp` skill. It reads the
  same facts and the prose of the same strategies and reconciles them
  where arithmetic cannot. It runs when you ask it to, never on its own,
  on your subscription.

Two inputs are written by hand: the playbook, the only one the solver
reads, and the owner's recorded matches, one map each, which the door's
`record_match` stores and `facts.matches` reads back as `Match` records. A
pull tool fills every other table. The matches judge the playbook
([How the playbook is judged](#how-the-playbook-is-judged)) and never
change it. The shipped playbook is six assumptions and one scored rule,
`heal-rate` ([The healing floor](#the-healing-floor)), while it is
rebuilt from the citations in
[inference/README.md](../inference/README.md); the default engine scores
every board beneath it ([The objective](#the-objective)). The
solver tests run on the reference playbook in
[tests/fixtures/playbook/](../tests/fixtures/playbook/), which holds a
file of every form but the draft. The package's map is the
[inference/__init__.py](../inference/__init__.py) docstring, and each
module's docstring holds its detail.

## The objective

The solver maximises one number per six, the default engine's terms
first and the playbook's on top:

```
score(six) = base(six) + the playbook's terms (How a strategy file works)
base(six)  = W_RATE x rates + W_SYNERGY x synergy + W_COUNTER x counters
```

`base` is the default engine, `inference/base.py`. It is always on and
needs no playbook, so a playbook of assumptions alone gets the sixes its
three terms favour, scored and explained:

- **rates**: each pick's all-ranks win rate on the map - its overall rate
  with no map, or no row for it there - as points over 50, times
  `p / (p + RATE_PICK_HALF)` for its pick rate `p` on the same footing,
  averaged over the six. A rarely picked hero's rate rests on few
  matches, so its edge is pulled toward a coin flip; `RATE_PICK_HALF` is set
  so that only the rarest heroes lose more than half their edge. The term is centred on 50
  and not on the reference sample's mean: the zero is the same on every
  board and needs no sample, and a comp's share of the optimal is its
  share of the optimal's edge over a coin flip.
- **synergy**: `team.synergy_score`, the wiki's synergy scores among the
  six.
- **counters**: the counter graph between the six and the other side,
  the weight of its answers less the weight of its exposures. A wiki
  edge, from the Match-Up tables or the Strategy sections, weighs 2.
  Where the wiki has no edge either way, `facts/counters.py` derives
  answers from the kits at load: thirteen mechanisms (anti-air, a flier,
  barrier piercing, anti-heal, burst, control, a projectile eater and a
  weapon it cannot take, armor, dive, saves, reach, tank-busting) score
  every ordered pair of released heroes, and each loser's six best
  answers, scoring 0.5 or more and more than the reverse, weigh 1 each.
  The other side is its locked picks, or, with none, its likely six on
  this map past the bans (`compute.expected_picks`, the six the board's
  red panel shows); either seat reads the other the same way. Only this
  term reads the likely six or a derived edge: the `team.*` and `enemy.*`
  counter metrics read the wiki's graph against the picks. The board
  names every derived edge it counts with the mechanism and the numbers
  that fired.

`W_RATE` is 1, so the rate term is in win-rate points. `W_SYNERGY` and
`W_COUNTER` are set so that each term's median spread across a board's
reference sample is about half the rate term's; the module docstring holds
the calibration, and recorded match outcomes are to refit it. A heuristic
still moves a six by its weight at most; the math page says how that
compares with the base's spread. Each term is a bar of the breakdown,
with the fact it read: the counter bar's fact names the six it read.

A `BaseWeights` rides the `Brief`, and `infer` and `evaluate`'s `base`,
into every `Objective` and every worker's `Spec`; `base.OFF` turns the
engine off, and a board is the playbook's alone, as it was before the
engine had a base. The board, the MCP tools and the inference service run
`DEFAULT`. The tests that pin the reference playbook's sixes turn it off,
and the validation rescores the playbook alone. With the engine off and a
playbook that scores nothing, every six ties at zero and a board reads
*unscored*.

## How a strategy file works

Drop a markdown file into `strategies/` and it is live: the solver reads
the directory on every call, the board's playbook panel shows it, the
`strategies` tool and the `strategy://` resources serve it, and
`load_authored` mirrors it into the `strategies` table. The frontmatter
is the whole contract:

```markdown
---
name: Answer every revealed enemy
kind: heuristic
category: matchup
direction: maximize
metric: team.coverage_share
weight: 3
when: enemy.size >= 1
---
# Answer every revealed enemy
The share of revealed enemies at least one of our picks answers...
```

That is the reference playbook's `coverage.md`, cut short. A `#`
comment takes a whole line: after a value, it is read as part of the
value.

| kind | form | frontmatter | what the solver does |
| --- | --- | --- | --- |
| heuristic | | `metric`, `direction` (`maximize` or `minimize`), `weight`, optionally `confidence` | normalises the metric to [0, 1] on the board's scale (flipped for minimize) and adds `weight x norm` |
| constraint | limit | `require: <expr>`, optionally `soft: true` and `penalty: <number>` | discards a candidate that fails; a soft one subtracts the penalty |
| constraint | scored | `bonus: <expr>` and/or `penalty: <expr>` | adds `weight x (bonus - penalty)` |
| assumption | | nothing: prose by definition | nothing: the solver takes it as given and the agent holds a comp to it |
| constraint or heuristic | draft | name, kind and prose only | nothing yet: shown and served until `/strategy` infers the rest or turns it into an assumption |

A constraint or a heuristic takes an optional `when` guard and applies
only where it holds. A heuristic guarded on the six's own state
(`team.*` or `matchup.*`) is a need: it adds `weight x (norm - 1)`, so
met it costs nothing and unmet it costs its weight, and the needs on one
guard cost `NEED_BUDGET` (2) together at most. The scale is a seeded
sample of 1200 legal sixes plus the field of each role's top six by the
board's prior (`inference/scale.py`), and `confidence` names a second
metric that scales the weight by how strongly the premise holds.

A strategy's prose is three sentences at most (`add_strategy` refuses
more): the claim, why and when, what is measured.

Expressions are a whitelist, compiled once and validated against the
metrics registry when the catalog loads: the `team`, `enemy`, `matchup`,
`map`, `world` and `params` sections, arithmetic, comparisons, `and`,
`or`, `not`, `x if c else y`, and `min`, `max`, `abs`, `round`, `len`,
`int`, `float`, `bool`. A key that is not in the registry, or a
`params.NAME` not declared under `params:`, is refused at load, so a typo
never scores silently. A key a section lacks reads 0, and a division,
floor division or remainder by zero reads 0 for that operation alone.
`params:` (an indented block of NAME: number) are the dials an expression
reads as `params.NAME`. Every key a strategy may reference is in the
vocabulary generated at the end of this document.

The solver never infers a formula or a weight from prose; a model does.
The `/strategy` skill turns a name, a kind and up to three sentences into
frontmatter, or into `kind: assumption` where nothing is measurable, and
stores it through `add_strategy`. A file dropped in with only a name, a
kind and prose is a draft, which `/strategy` completes through
`infer_strategy`. Where the claude CLI is signed in - the host -
`derive.py` completes drafts headless on `claude -p` when
`load_authored`, `orchestrator.py up` or `derive_strategies` runs. No
API key anywhere.

## How the weights move

Weights do not learn on their own. The recorded matches judge the
playbook and move nothing; [pm/backlog.md](../pm/backlog.md) holds what
learning from them would take. The default engine's weights are constants
in `inference/base.py`, and no slider moves them. The
board's sliders override a weight for one board - `weights=<id>:<0..10>`
on `/board`, `weights` on the `board` tool - and every result names the
weights it was scored under. Four tools write a strategy file - `tune`,
`add_strategy`, `infer_strategy` and `derive_strategies` - each validated
through the catalog before it writes and logged with its reason in
`strategies/tuning-log.md`; a slider's *store* is a `tune` call, which
the board offers only with `COUNTRIX_READ_ONLY=0`.

## The healing floor

`heal-rate`, the shipped playbook's one scored rule, holds a six to a
healing threshold set by the kit. It reads `matchup.heal_shortfall`;
`facts/compute.py` computes it and `matchup.heal_need` (`heal_read`,
`heal_need`, `heal_shortfall`), and the board words both in one fact.

The model is a race. A six has a pool P (`team.pool_total`: health,
shield, armor and a form's armor), damage D (`team.dps_floor`) and
healing onto teammates H (`team.hps_floor`, sustained, reloads in). Each
side's damage lays the same anti-heal k on the other's healing, so blue
loses (D_r - k H_b) / P_b of its pool a second and red
(D_b - k H_r) / P_r. Blue wins the race when red loses the larger share,
and the margin splits in two:

```
margin = [D_b / P_r - D_r / P_b]  +  k [H_b / P_b - H_r / P_r]
          the damage half             the healing half
```

The damage half is 1/`chew_time_ours` - 1/`chew_time_theirs`. The healing
half breaks even when blue heals the same share of its own pool a second
as red heals of its own, and k cancels there. That share times blue's
pool is the need, floored at red's healing in full:

```
need      = max(H_r, H_r / P_r x P_b)
shortfall = max(0, need - H_b) / need         0 when need is 0
charge    = 2 x shortfall                     heal-rate's weight
```

The floor is there because parity alone asks less healing of a smaller
six, and the race never rewards a smaller pool: its margin rises with
P_b. Under parity alone the engine drops a tank to slip under the bar;
the floor stops that. The margin also rises with every support added, so a rule
that maximised healing would drive toward five supports; a floor does not.

**Red as read.** Red's locked picks, and each open slot a role the 2-2-2
(`EXPECTED_SHAPE`) still misses: d_r = max(0, 2 - red's count in r),
spread over the open slots as f = open / sum(d_r), each missing seat at
its role's median pool (`World.pool_medians`, a form's armor in) and a
missing support at half `world.hps_bench`, the median support's healing:

```
H_r = enemy.hps_floor  + f x d_support x hps_bench / 2
P_r = enemy.pool_total + f x sum over r of d_r x pool_medians[r]
```

A red that has shown its two supports reads as two, not as two and a
share of a third. A complete red that heals nothing needs nothing. The
likely six is not read: it rests on pick rates.

**The threshold.** With red empty, red is the 2-2-2 of role-median
heroes: H_r = `world.hps_bench` = 134.34 hp/s and P_r = `world.pool_ref`
= 2 x (525 + 250 + 237.5) = 2025, the 6v6 kit as of 2026-09-25. A six
must heal 6.63% of its own pool a second, and never less than 134.34
hp/s. Everything in it is kit data; no rate enters. The sources hold no
absolute winning threshold - no fight length, no ultimate charge - so
the rule promises parity with the other side's healing and nothing more.
At parity the race is the damage half's, which no shipped rule prices.

**What it moves.** A six with one support falls under the bar against
any red that heals, so the engine answers with a second support and keeps
a third only where the pair heals little. Within a board the shortfall
mostly follows the support count; the rest is how much the pair heals,
which a count would miss. The weight, 2, sets a six at full shortfall
beside the synergy and counter terms, which each spread a typical board's
sixes about 2.1 points (`inference/base.py`).

**What it inherits.** The bar is only as good as `hps`. The World counts
an area heal at one target, so pairs with Lucio, Brigitte or Mizuki fall
under the bar 78-100% of the time and the engine answers with a third or
fourth support; a beam healer's `hps` (Illari, Moira, Wuyang) sits above
what its resource sustains. Perks, ultimates, self-healing and health
packs are out, on both sides alike. A World-wide error cancels, since
the bench moves with it; an error on one hero does not.

## How the playbook is judged

The owner plays on console, so a match is entered by hand after the
game: one map, with both sixes as they stood longest on the field, the
bans, the map, blue's side and blue's result. Blue is always the owner's
team. Each map carries the digest of the playbook in force when it was
played (`catalog.playbook_digest`). `validate.py` asks one question of
them: does the playbook's score say anything about who won that the
heroes alone do not? `rescore.py` picks the maps and runs them through the
engine, `predict.py` holds the models, the splits and their scores,
`fit.py` the statistics under them, and `report.py` the answer as JSON and
as text. It runs as the `validate_playbook` tool, or as
`.venv/bin/python -m ui.validation`, which prints the same text and
writes a page of charts and its JSON to `db/raw/validation.html`. Nothing
it runs writes to the database or the playbook.

**The rescore.** Each map goes through `evaluate` from both seats: blue's
six against red's on blue's side, red's against blue's on the other
side. Each seat's score is the playbook's objective on its own seat's
scale, with the default engine off: the question is what the playbook
adds, and M2 already reads the rates and M3 the heroes. The two are the
same kind of number, and their difference is the playbook score
difference. The team metrics of both sixes and the
matchup metrics ride along. A map the engine refuses - a hero the
database no longer holds, a board no six satisfies - is listed, not
judged. About three seconds a map on the real roster.

**The pin.** A playbook is judged only on the maps from the first one
played under its digest on. The maps before it are the ones it may have
been tuned on, and judging a playbook on the maps it was fitted to is the
leak that makes any rule look good. A tune makes a new digest, which
starts with no maps of its own. `pin: false` (`--all`) judges every map
and the report says so.

**The models.** Five, each fitted on some maps and scored on others:

| model | reads |
| --- | --- |
| M0 | nothing: a coin flip |
| M1 | the map and side's win rate, shrunk toward the overall one by four maps' worth |
| M2 | blue's `team.map_win_mean` minus red's: Blizzard's rates, for personal use |
| M3 | one effect per hero, +1 on blue and -1 on red, in a ridge-penalised logistic model |
| M4 | M3 plus the playbook score difference and the matchup metrics |

The ridge pulls every coefficient but the intercept toward 0 with a prior
sd of 0.25 log-odds, so a hero's effect or a feature's effect per sd is
earned from the maps. The intercept is the owner's own win rate. A
feature other than a hero's is standardised on the maps the fit trains
on. The fit is Newton's method in pure Python (`fit.py`); nothing is
installed for it.

**The splits.** The time split cuts the sessions (a session is one
`played_on` date) into five blocks of about equal maps and scores each
block after the first with a fit on every block before it: no fit trains
on a map played on or after a day it scores. The sessions split deals the
sessions into ten folds (one per session where there are fewer) and
scores each with a fit that left it out. A split needs two sessions.

**The scores.** Log loss (a coin flip scores ln 2, 0.693) and Brier (a
coin flip scores 0.25), each with a 95% interval from 2000 resamples of
whole sessions, since maps played the same evening are not independent.
Every interval on a split draws the same resamples, so the difference
between two models is paired: M4 minus M3 is what the playbook score and
the matchups add to the heroes.

**The ablations.** M4 is fitted again with one family of strategies
dropped from the playbook score, then with the score dropped whole. A
family is read off the catalog, each scoring strategy filed in the first
it fits, and named by the ids it drops:

| family | holds |
| --- | --- |
| side | the side bonuses: a strategy that reads `map.side` |
| counters | a strategy on the counters table's edges (`team.coverage`, `team.exposed_count`, ...) |
| synergy | a strategy on the wiki's synergy pairs |
| rates | a strategy that reads Blizzard's win, pick or ban rates |
| scored | the other scored constraints |
| other | the rest that scores: kit heuristics and soft limits |

A family is dropped by taking its terms out of both seats' scores; each
heuristic stays normalised on the full playbook's scale. An ablation
whose log loss rises over M4's was carrying weight.

**The guard.** An effect of b log-odds per sd needs about (5.6 / b)^2
decided maps to be told from none (a two-sided 5% test at 80% power): 191
for an even map won 60% of the time, 779 for 55%. Below that the report
says how many decided maps there are and how many the effect needs, and
gives no verdict; the scores still show, with their intervals. A draw is
judged but never decided. `effect` sets the win chance the guard sizes
the sample for.

**What it cannot tell you.**

- Why a comp wins. A score that predicts results may ride on something
  the comps share - the owner plays some heroes better - and the models
  cannot tell the playbook's reason from that one.
- Anything about other players. Blue is always the owner's team: a hero's
  effect is the hero and the owner's hands on it together, at one rank,
  in one region, on console.
- What happened inside a map. The sixes are the ones on the field
  longest; a swap, a stage, an ult and a disconnect are not recorded.
- A small effect from a few maps. Matchmaking pulls every lobby toward
  even, which shrinks every effect, and most effects worth having need
  hundreds of decided maps.
- What a re-solved playbook would score. An ablation drops a family's
  terms from the scores the full playbook gave; it does not solve the
  board again without them.
- Whether to tune. A tune read off a verdict is fitted to the maps that
  gave it; the pin judges the tuned playbook only on the maps that come
  after.

The page and the JSON carry figures derived from Blizzard's rates (M2,
each map's win difference). They are the owner's alone: `db/raw` is
gitignored, and nothing public shows them.

## The catalog

<!-- generated:catalog -->
7 files in `inference/strategies/`: 1 constraints (0 limits, 1 scored), 0 heuristics and 6 assumptions. Regenerated by `.venv/bin/python -m door.mcp call db_docs`.

#### Constraints

##### Heal at the other side's rate (`heal-rate`, sustain, scored)

weight 2; penalty `matchup.heal_shortfall`

A six heals at least the share of its total health that the other side heals of its own each second, and never less than the other side's healing in full; an unrevealed slot on that side is the 2-2-2 shape's missing role at the role's median pool and healing. With damage anti-heal on both sides, the healing half of the race between the two sixes breaks even at that share, and nothing in the kit sets a higher bar. The charge is the weight times the share of the need left unhealed.

#### Assumptions

##### This is Open Queue Ranked (`open-queue-ranked`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

The mode is Competitive Open Queue, 6v6: six picks per side in any mix of roles under the queue's own limit of two tanks. Rules written for Role Queue's 2-2-2 or for Quick Play do not bind here. Nothing is measured; the shape rules read from this.

##### All players play optimally (`players-play-optimally`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

Every player on both teams plays their hero as well as it can be played. A strategy therefore encodes the game - kits, ranges, cooldowns, maps, roles - and never a lobby's habits or a rank's tendencies. Nothing is measured; the session holds every comp to it.

##### Console only (`console-only`, general)

*assumption* - prose the solver takes as given and the session holds a comp to

The owner plays on console, and the playbook is built for console play. The rates are the console pull, the recorded maps are console maps entered by hand, and no PC-only feature such as the Workshop Inspector log is assumed. Nothing is measured.

##### The rates are a console pull (`console-pull`, uncertainty)

*assumption* - prose the solver takes as given and the session holds a comp to

The pick, win and ban rates the board reads were captured for console play, not PC. A comp is built for console hands, and a PC figure is never assumed in its place. Nothing is measured.

##### Not rank specific (`rank-agnostic`, uncertainty)

*assumption* - prose the solver takes as given and the session holds a comp to

The playbook applies at every rank alike: the rates are the all-ranks figures and no rule turns on a rank. A hero whose value swings by rank is noted as uncertainty, never as a rank's rule. Nothing is measured.

##### Region agnostic (`region-agnostic`, uncertainty)

*assumption* - prose the solver takes as given and the session holds a comp to

The playbook applies in every region alike. The rates it reads are one region's capture, a stated proxy for direction and never for decimals, and no rule turns on where a match is played. Nothing is measured.

#### The vocabulary

Every key a strategy may reference, with its meaning. `enemy.*` are
the `team.*` metrics computed for the red side.

| key | meaning |
| --- | --- |
| `team.size` | picks locked on this team |
| `team.open_slots` | slots still open (6 - size) |
| `team.tanks` | tank count |
| `team.damage` | damage count |
| `team.supports` | support count |
| `team.subrole_diversity` | distinct subroles / size (1.0 = every pick a different job) |
| `team.subroles` (text) | the subroles present |
| `team.shape_flags` (text) | TANKLESS / double tank / triple DPS / NO SUPPORT / solo heal |
| `team.style_counts` (text) | picks per playstyle tag (a hero can carry several) |
| `team.style_top` (text) | the modal playstyle among the picks |
| `team.style_lean` (text) | the playstyle a strict majority of picks carry, else none |
| `team.style_fit` | share of picks tagged with the map's rewarded style (0 without a map) |
| `team.shape_excess` | picks over EXPECTED_SHAPE's two per role |
| `team.pool_total` | team effective HP: sum of health + shield + armor, plus a form's armor by its uptime |
| `team.pool_min` | the weakest pick's pool - focus fire finds the minimum |
| `team.weakest` (text) | who holds the smallest pool |
| `team.armor_total` | summed armor, a form's by its uptime |
| `team.armor_share` | armor / pool |
| `team.shield_total` | summed recharging shields |
| `team.shield_share` | shields / pool |
| `team.squish_count` | picks at or under 250 pool |
| `team.squishies` (text) | the picks at or under 250 pool |
| `team.overhealth_total` | summed peak overhealth a kit can grant |
| `team.dps_floor` | summed published per-second damage figures (a floor: misses and healing ignored) |
| `team.dps_count` | picks whose kit publishes a per-second damage figure |
| `team.burst_max` | the biggest single hit on the team, a headshot where one counts |
| `team.one_shots` | picks whose biggest hit, not a melee swing, kills a 250-pool hero |
| `team.burst_hero` (text) | who holds the biggest single hit |
| `team.burst_ranged` | the biggest single hit from a pick that is not melee-only |
| `team.ult_damage_total` | summed max damage across the team's damage ultimates |
| `team.dmg_ults` | ultimates that carry a damage figure |
| `team.ult_cost_mean` | mean ultimate charge cost where published |
| `team.hitscan` | picks with a hitscan weapon or ability |
| `team.hitscan_reach` | hitscan picks whose weapon publishes a reach of 30 m or more |
| `team.projectile` | picks whose weapons are projectile |
| `team.beam` | picks with a damaging beam |
| `team.melee` | picks with a melee weapon |
| `team.aoe_count` | kit pieces tagged area of effect or shockwave |
| `team.aoe_damage_count` | kit pieces that damage an area |
| `team.range_median` | median of each pick's longest published range |
| `team.range_max` | the longest range on the team |
| `team.range_min` | the shortest longest-range |
| `team.dmg_amp` | picks that amplify someone's damage |
| `team.hps_floor` | summed sustained healing onto teammates, hp per second, reloads in |
| `team.heal_peak_total` | summed biggest single heal per pick, its own self-heal included |
| `team.heal_peak_supports` | summed biggest single heal (one cast, hp) across the supports |
| `team.heal_peak_max` | the biggest single heal a teammate can receive |
| `team.heal_ratio` | support heal peak / the roster's two-support bench |
| `team.hps_supports` | summed sustained healing across the supports, hp per second |
| `team.hps_ratio` | support sustained healing / the roster's two-support bench |
| `team.heal_amp` | picks that amplify healing |
| `team.antiheal` | picks with anti-heal |
| `team.cleanse` | picks with a cleanse |
| `team.invuln` | picks with an invulnerability or a death-prevention |
| `team.team_cleanse` | picks with a cleanse that lands on a teammate |
| `team.team_saves` | picks with an invulnerability, death-prevention or cleanse that lands on a teammate |
| `team.lifelines` | picks carrying any healing at all, their own and lifesteal included |
| `team.cooldown_median` | median cooldown across every ability on the team |
| `team.cooldown_count` | cooldowns counted |
| `team.cc_count` | picks with crowd control (stun, sleep, immobilize, hinder, knockback) |
| `team.mobility_count` | picks with a movement or evasive ability |
| `team.flyers` | picks that fly or hover |
| `team.light_flyers` | picks that fly or hover, tanks aside |
| `team.barrier_hp` | summed barrier health the team fields |
| `team.barrier_count` | picks with a barrier |
| `team.barrier_piercers` | picks whose kit ignores barriers |
| `team.pierce_dps` | summed damage of the picks whose kit ignores barriers |
| `team.deployables` | picks with deployables |
| `team.synergy_edges` | the wiki's synergy pairs among the picks |
| `team.synergy_score` | summed synergy scores among the picks |
| `team.synergy_density` | synergy edges / possible pairs |
| `team.isolated_count` | picks with a documented partner somewhere and none on the team |
| `team.isolated` (text) | the isolated picks |
| `team.core_size` | largest connected group in the team's synergy graph |
| `team.pairs` (text) | the synergy pairs present |
| `team.win_mean` | mean all-ranks win rate |
| `team.pick_mass` | summed all-ranks pick rate |
| `team.availability` | chance every pick survives the ban screen: product of (1 - ban) |
| `team.map_availability` | the same from this map's ban rates (the all-ranks ban where a map publishes none; equal to availability without a map) |
| `team.max_ban_rate` | the highest ban rate on the team |
| `team.max_ban_hero` (text) | who carries the highest ban rate |
| `team.rank_sensitive_count` | picks whose win rate swings 6+ points across ranks |
| `team.trend_sum` | summed win-rate movement since the rates last changed |
| `team.map_known` | 1 if a map is set |
| `team.map_win_mean` | mean win rate on the map (the all-ranks mean without a map) |
| `team.map_pick_mass` | summed pick rate on the map |
| `team.map_specialists` | picks running 2.5+ points over their own baseline here |
| `team.map_offmap` | picks running 2.5+ points under their own baseline here |
| `team.home_map_hits` | picks whose three best maps by rate include this map |
| `team.coverage` | enemies answered by at least one pick |
| `team.coverage_share` | coverage / enemies revealed |
| `team.unanswered` (text) | enemies no pick answers |
| `team.answer_edges` | (enemy, pick) counter edges: picks answering enemies |
| `team.exposure_edges` | (pick, enemy) counter edges: enemies answering picks |
| `team.exposed_count` | picks answered by at least one enemy |
| `team.exposed` (text) | the exposed picks |
| `team.safe_count` | picks no enemy answers |
| `team.net_edges` | answer edges minus exposure edges |
| `team.double_covered` | enemies answered by two or more picks |
| `team.banproof_coverage` | coverage recomputed without the highest-ban answerer |
| `matchup.pool_diff` | blue effective HP minus red |
| `matchup.dps_diff` | blue damage floor minus red |
| `matchup.hps_diff` | blue healing floor minus red |
| `matchup.burst_vs_heal` | blue's biggest hit minus red's biggest single save |
| `matchup.heal_vs_burst` | blue's biggest single save minus red's biggest hit |
| `matchup.chew_time_ours` | seconds of blue's floor damage to chew red's pool (999 if unknown) |
| `matchup.chew_time_theirs` | seconds of red's floor damage to chew blue's pool |
| `matchup.tempo_diff` | red median cooldown minus blue's (positive: blue cycles faster) |
| `matchup.range_diff` | blue median reach minus red's |
| `matchup.exposure_share` | share of blue answered by red |
| `matchup.ult_answers` | blue invulnerabilities plus cleanses |
| `matchup.heal_need` | hp/s blue must heal: red's healing per pool times blue's pool, at least red's healing; red's open slots read as the 2-2-2's missing roles |
| `matchup.heal_shortfall` | share of heal_need blue's healing floor leaves unhealed, 0..1 (0 when nothing is needed) |
| `map.known` | 1 if a map is set |
| `map.sided` | 1 if the mode has an attacking and a defending side (Escort, Hybrid) |
| `map.side` (text) | this seat's side on a sided map: attack, defense, or empty |
| `map.style_top` (text) | the playstyle the map rewards most: the rates' lift plus the terrain's lean |
| `map.style_margin` | top style score minus the runner-up, in sd |
| `map.mode` (text) | the game mode |
| `map.stages` | separate arenas, one played at a time: Control's 3, Flashpoint's 5; else 0 |
| `map.phases` | named parts of one route, played in order: Hybrid's 2, an Escort map's named stretches; else 0 |
| `map.bans` | bans already made in this match: a ban rate is a risk only before them |
| `map.chokes` | chokepoints, narrow streets, corridors, tunnels, gates and doorways: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.interiors` | rooms, caves and other indoor ground: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.high_ground` | high ground, rooftops, balconies and other vertical ground: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.flanks` | flank routes and side paths: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.sightlines` | long sightlines: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.open_ground` | open ground and ground said to lack cover: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.hazards` | drops, pits and other environmental hazards: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.cover` | cover: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `world.heal_bench` | 2 x the median peak heal across the released supports |
| `world.hps_bench` | 2 x the median sustained healing across the released supports |
| `world.pool_ref` | the pool of a 2-2-2 of role-median heroes: 2 x each role's median pool, a form's armor in, summed |
| `world.roster_size` | heroes in the roster |
<!-- /generated:catalog -->
