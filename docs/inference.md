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

The playbook is the only input written by hand; a pull tool fills every
other table. The shipped playbook is five assumptions that score nothing,
so a board reads unscored while the playbook is rebuilt from the
citations in [inference/README.md](../inference/README.md). The solver
tests run on the reference playbook in
[tests/fixtures/playbook/](../tests/fixtures/playbook/), which holds a
file of every form but the draft. The package's map is the
[inference/__init__.py](../inference/__init__.py) docstring, and each
module's docstring holds its detail.

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

Weights do not learn on their own: no match signal is recorded, and
[pm/backlog.md](../pm/backlog.md) holds what learning would take. The
board's sliders override a weight for one board - `weights=<id>:<0..10>`
on `/board`, `weights` on the `board` tool - and every result names the
weights it was scored under. Four tools write a strategy file - `tune`,
`add_strategy`, `infer_strategy` and `derive_strategies` - each validated
through the catalog before it writes and logged with its reason in
`strategies/tuning-log.md`; a slider's *store* is a `tune` call, which
the board offers only with `COUNTRIX_READ_ONLY=0`.

## The catalog

<!-- generated:catalog -->
5 files in `inference/strategies/`: 0 constraints (0 limits, 0 scored), 0 heuristics and 5 assumptions. Regenerated by `.venv/bin/python -m door.mcp call db_docs`.

#### Assumptions

##### This is Open Queue Ranked (`open-queue-ranked`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

The mode is Competitive Open Queue, 6v6: six picks per side in any mix of roles under the queue's own limit of two tanks. Rules written for Role Queue's 2-2-2 or for Quick Play do not bind here. Nothing is measured; the shape rules read from this.

##### All players play optimally (`players-play-optimally`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

Every player on both teams plays their hero as well as it can be played. A strategy therefore encodes the game - kits, ranges, cooldowns, maps, roles - and never a lobby's habits or a rank's tendencies. Nothing is measured; the session holds every comp to it.

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
| `world.roster_size` | heroes in the roster |
<!-- /generated:catalog -->
