# The strategies

The inference layer's brain: 38 markdown files in `inference/strategies/`
(18 constraints - 3 limits, 10 scored, 5 prose - and 20 heuristics). Each file is
frontmatter a machine scores by and prose a person argues with; the
solver reads the files live, and `load_authored` mirrors them into the
`strategies` table so a recommendation can cite the ids it was scored
under. Tuning is editing a file (the compose stack bind-mounts the
directory, so the `inference` container picks edits up live). This
page is generated: `python -m db.mcp call db_docs`. Every change to a
file goes through the `tune` tool (or a `fit_weights` nudge) and is logged
in [tuning-log.md](../inference/strategies/tuning-log.md).

## How a composition is scored

```
FACTS      = HEROES ∪ MAPS ∪ META
STRATEGIES = CONSTRAINTS ∪ HEURISTICS
COMP       = ARGMAX[ STRATEGIES( FACTS ) ]
```

For a board (map, red picks, locked blue picks) the solver enumerates
candidate sixes around the locked picks, computes every team, enemy and
matchup metric for each (the same functions the board renders as facts),
then:

- **constraints** come in three forms. A *limit* (`require`) discards a
  candidate that fails it (a soft one subtracts its `penalty` instead);
  a *scored* constraint adds `weight x (bonus - penalty)` while its `when`
  holds; a *prose* constraint (`prose: true`) adds nothing - the session
  reads it and the board shows it;
- **heuristics** min-max normalise their `metric` to [0, 1] against a seeded
  reference sample of random legal sixes for the board (flipped for
  `minimize`) and add `weight x norm` - one scale per board, so infer,
  evaluate and the current comp agree.

Score = the sum. Players are assumed to play optimally, so the score is
a comp's ceiling, not a prediction for a given lobby.

A file with only a name, a kind and prose is a *draft*: shown and served,
ignored by the solver, until the `/strategy` skill infers its frontmatter
from the prose and writes it through `infer_strategy`.

## Catalog

### Constraints

#### Fliers need a hitscan answer (`anti-air`, matchup, limit)

`require team.hitscan >= 1` (soft, penalty `2.5`); when `enemy.flyers >= 1`

When the enemy fields a hero who flies or hovers, a comp with no hitscan
weapon answers them with projectiles and hope. The data layer tags
flight from the kit's own keywords and descriptions, and hitscan from
the weapon configs, so this is measured, not judged.

Soft, because a barrier-and-brawl comp can sometimes deny the ground a
flier's team needs - but that argument has to beat a 2.5-point penalty.

#### Do not build on a near-certain ban (`ban-safety`, meta, limit)

`require team.max_ban_rate < params.BAN_CERTAIN` (soft, penalty `2.5`)
params: BAN_CERTAIN=35

A hero banned in more than a third of lobbies is a plan that usually
does not survive the ban screen. Soft rather than hard: when that hero
is the only answer to what the enemy fielded, the rest of the score can
still carry the comp, but it pays for the risk up front.

Pair with `availability`, which prices every pick's ban rate smoothly;
this file is the cliff, that one is the slope.

#### At most two tanks (`open-queue-tanks`, shape, limit)

`require team.tanks <= 2` (hard)

The game is 6v6 Open Queue: six picks, any mix of roles, with the one
limit the queue itself enforces - no more than two tanks. That limit is
the only shape limit the solver applies. Everything else about a
comp's shape (no support, four damage, a single frontline) is scored, not
forbidden: the shape flags on the board name it, `under-healed` and
`squish-limit` charge for it, and the heuristics decide whether it is worth
the price.

To search Role Queue's 2-2-2 instead, tighten this file to
`require: team.tanks == 2 and team.damage == 2 and team.supports == 2`.

#### Do not field a whole team of dive bait (`squish-limit`, durability, scored)

weight 1; penalty `max(0, team.squish_count - 4) * 1.0`

Picks at or under 250 pool are one-dive targets. Four of them is the
standard 2-2-2 shape of a 6v6; every one past that is a target the
enemy's optimal play will find first.

#### Shut off a heavy heal line (`anti-heal-answer`, matchup, scored)

weight 1; when `enemy.heal_ratio >= params.HEAL_RATIO`; bonus `min(team.antiheal, 1) * 1.5`
params: HEAL_RATIO=1.0

When their support line heals at or above the roster bench, one
anti-heal pick (a negative healing modifier in the kit - the grenade,
the discord of healing) is worth more than another damage dealer. One
is rewarded; two overlap.

#### Bring barrier-piercers when they wall up (`barrier-answer`, matchup, scored)

weight 1; when `matchup.barrier_need >= params.BARRIER_HP`; bonus `min(team.barrier_piercers, 2) * 1.0`
params: BARRIER_HP=600

When the enemy fields serious barrier health, picks whose kit ignores
barriers (the wiki's `ignores_barrier` flag and keywords) restore the
damage math. Up to two are rewarded; a third is redundancy the heuristics
already price.

#### Punish a one-note enemy comp (`counter-the-lean`, matchup, scored)

weight 1; when `matchup.style_lean_red == 'dive'`; bonus `min(team.cc_count, 2) * 0.5 + min(team.barrier_count, 1) * 0.5`

When a strict majority of the revealed enemies carry the dive tag, the
answer is peel and a wall to dive into: crowd control and a barrier.
The `peel-against-dive` constraint reads engage tools; this one reads the
judged style, so both fire against a real dive comp and only one
against a coincidence.

#### Peel when they dive (`peel-against-dive`, matchup, scored)

weight 1; when `enemy.mobility_count >= 2`; bonus `min(team.cc_count, 3) * 0.75`

Two or more enemy picks with engage tools means the backline gets
jumped. Crowd control - stuns, sleeps, immobilizes, knockbacks, read
from the kits' keywords - is what turns a dive into a dead diver. Up
to three peel tools are rewarded.

#### Have an answer to their all-in (`ult-answers`, matchup, scored)

weight 1; when `matchup.ult_threat >= params.THREAT`; bonus `min(matchup.ult_answers, 2) * 0.75`
params: THREAT=300

When the enemy's damage ultimates stack past the threshold, an
invulnerability or a cleanse (lamp, suzu, the transcendence of a
support) is the difference between losing a fight and losing a fight
plus the next one. Two answers rewarded.

#### A dive comp needs to arrive together (`dive-needs-mobility`, shape, scored)

weight 1; when `map.style_top == 'dive' or team.style_lean == 'dive'`; bonus `min(team.mobility_count, 5) * 0.5`

On a map that rewards dive, or when the picks already lean dive, every
pick with a movement tool is one who arrives with the engage instead of
watching it from the choke. Five rewarded; the sixth is the anchor.

#### Attackers need to break a hold (`attack-breaks-the-hold`, side, scored)

weight 1; when `map.side == 'attack'`; bonus `min(team.mobility_count, 4) * 0.5 + min(team.antiheal, 1) * 0.5`

On the attacking side of an Escort or Hybrid map the fight starts at a
choke the defenders chose. Engage tools (movement, evasive, flight) let
the comp arrive on the high ground instead of walking into it, and one
anti-heal pick turns a held position into a trade the defenders lose.

The rates do not split by side, so this is a judgement about the kits,
not a measured advantage - which is why it is a scored constraint with a small
bonus rather than a heuristic.

#### Defenders hold ground (`defense-holds-the-ground`, side, scored)

weight 1; when `map.side == 'defense'`; bonus `min(team.deployables, 2) * 0.5 + min(team.barrier_count, 2) * 0.5 + (0.5 if team.range_median >= 20 else 0)`

On the defending side the geometry is yours: deployables (turrets,
walls, lamps) and barriers make a choke expensive to cross, and reach
lets the comp chip the approach before the attackers can commit.

Judged from the kits, like its attacking twin, and weighted the same:
enough to tilt a close call between two comps the heuristics rate alike,
never enough to override coverage or cohesion.

#### Two supports must actually heal (`under-healed`, sustain, scored)

weight 1; when `team.supports >= 2 and team.heal_ratio < params.HEAL_MARGIN`; penalty `2`
params: HEAL_MARGIN=0.75

The support line's summed peak single heal against the roster's
two-support bench (twice the median support's peak). Below the margin
the line is complete and still light - two Zenyattas is a choice, and
this constraint makes the solver pay for it rather than stumble into it.

#### Locked picks are given, not chosen (`locked-picks`, assumptions, prose)


A blue pick that is locked is in the comp. The solver never trades it
away, the facts profile it (partners, who answers it, how it runs here)
and the WARNING facts say when a revealed enemy answers it - at which
point the open slots must cover for it, and the score says how well
they do.

#### What the score is (`objective`, assumptions, prose)


For every candidate six, the solver computes the same team, enemy and
matchup metrics the board shows as facts, then sums: each heuristic's weight
times its metric normalised to [0, 1] across the candidates (flipped
for minimize), plus each scored constraint's weight times its bonus minus
penalty while its condition holds, minus soft limits' penalties. Hard
limits prune before any of that. A constraint with neither a limit nor a bonus
or penalty is prose alone - the session reads it, the board shows it.
STRATEGIES = CONSTRAINTS ∪ HEURISTICS; the score is STRATEGIES( FACTS ).

To tune, edit a file: raise a weight, add a `when`, change a threshold
under `params`. The catalog is validated on load - a metric name that
does not exist is an error, not a silent zero - and `db_docs`
regenerates docs/strategies.md from the files.

#### Players play optimally (`optimal-play`, assumptions, prose)


The central assumption of this layer: every player on both teams plays
their hero to its ceiling. The score is therefore a comp's ceiling, not
a prediction for a lobby - no comfort-pick discount, no "nobody hits
Widow at this rank", no skill gap.

Everything that relaxes this will arrive as more granular data (rank
tiers already exist on the board as RANK-SENSITIVE facts) and as
strategies that read it. Until then, argue against the optimum, not
against a guess about the players.

#### Rates are Role Queue, console, Americas (`rates-are-a-proxy`, uncertainty, prose)


Every win, pick and ban rate was measured on Competitive Role Queue,
console, Americas, under the patch and season on the snapshot fact.
That is the closest published proxy for 6v6 Open Queue and it is stated
every time rather than assumed away. Lean on rates for direction, not
decimals; a RANK-SENSITIVE fact means the advice must know its
audience.

#### When patches shipped since capture, trust the kit (`vintage`, uncertainty, prose)


The board's first facts state when the rates were captured and warn
when patches have shipped since. Stale rates argue less: weight the
kit numbers, keywords and the authored playbook over win rates until
`pull_rates` runs again. The data layer makes that one tool call.

### Heuristics

#### Bring sustained damage (`damage-floor`, damage)

`maximize team.dps_floor` - summed published per-second damage figures (a floor: misses and healing ignored). weight 1

The sum of each kit's best published per-second damage figure. A floor,
stated as one: no misses, no falloff, no reloads folded in beyond what
the wiki's own figure states. It separates comps that can chew a tank
from comps that poke one.

#### Field more hit points (`effective-hp`, durability)

`maximize team.pool_total` - team effective HP: sum of health + shield + armor. weight 0.5

Team effective HP - health, shield and armor summed. The ceiling on what
the comp absorbs before the first death, ignoring healing. Lightly
weighted: pool is mostly decided by the shape constraint, and the
matchup heuristics already price what the enemy does to it.

#### Win on this ground (`map-fit`, map)

`maximize team.map_win_mean` - mean win rate on the map (the all-ranks mean without a map). weight 2

Mean all-ranks win rate of the six on the selected map (the roster-wide
win rate when no map is set, so the heuristic still ranks comps on a blank
board). Map rates are the closest measured thing to "this comp works
here"; specialists and off-map liabilities are the same numbers seen
per hero on the board.

#### Take the picks the playbook lists for this map (`playbook-map-picks`, map)

`maximize team.map_strategy_hits` - picks counterpick lists among their best maps here. weight 1; when `map.known == 1`

How many of the six appear in counterpick.gg's best-maps list for the
selected map. A second opinion on `map-fit` from a source that ranks
rather than counts; alignment with it is a cited argument.

#### Play the style the map rewards (`style-alignment`, map)

`maximize team.style_fit` - share of picks tagged with the map's rewarded style (0 without a map). weight 1.5; when `map.known == 1`

Share of picks tagged with the playstyle the map rewards most (the
authored `map_playstyle.csv`, top score). King's Row rewards brawl, so
a six of brawl heroes fits it fully; a poke comp there fights the
geometry as well as the enemy.

Judged, not measured - the wiki assigns styles and the operator scores
maps - which is why `map-fit` (measured) outweighs it.

#### Keep a kill window through their healing (`burst-window`, matchup)

`maximize matchup.burst_vs_heal` - blue's biggest hit minus red's biggest single save. weight 1; when `enemy.size >= 1`

Our biggest single damage figure minus their biggest single heal. When
it is positive, one cooldown deletes a target through the save; when it
is negative, every pick has to stack damage to kill anything, and
optimal-play enemies do not stand still for that.

#### Chew through them faster (`chew-time`, matchup)

`minimize matchup.chew_time_ours` - seconds of blue's floor damage to chew red's pool (999 if unknown). weight 1; when `enemy.size >= 1`

Their total pool divided by our damage floor: seconds of unmitigated
fire to delete the enemy team. Crude and labelled crude on the board -
no healing, no misses - but a two-to-one asymmetry in the floor is real
information about who wins a straight trade.

#### Answer every revealed enemy (`coverage`, matchup)

`maximize team.coverage_share` - coverage / enemies revealed. weight 3; when `enemy.size >= 1`

The share of revealed enemies at least one of our picks answers, from
the playbook's counters table. The single strongest lever the database
holds: a comp that answers all six has a plan for every fight, and one
that answers two is hoping the other four misplay.

Weighted highest because, under the optimal-play assumption, unanswered
enemies do not misplay.

#### Answer the dangerous ones twice (`double-coverage`, matchup)

`maximize team.double_covered` - enemies answered by two or more picks. weight 1; when `enemy.size >= 2`

Enemies answered by two or more of our picks. Redundant answers survive
a ban, a swap, or one of ours dying first; single-threaded answers do
not. Worth a point, not three: breadth (`coverage`) comes first.

#### Walk into no counter already on the field (`exposure`, matchup)

`minimize team.exposed_count` - picks answered by at least one enemy. weight 2; when `enemy.size >= 1`

How many of our picks a revealed enemy is listed as answering. Answering
two enemies means less when both of them also answer you; this is the
other half of `coverage`, and the pair together is the net matchup the
board shows.

#### Outrange them (`range-war`, matchup)

`maximize matchup.range_diff` - blue median reach minus red's. weight 0.75; when `enemy.size >= 1`

Our median longest reach minus theirs. Whoever outranges chooses the
fight's opening seconds and forces the approach, and the approach is
where brawls bleed. Positive means we open at distance; negative means
we close fast or trade cover.

#### Survive the ban screen (`availability`, meta)

`maximize team.availability` - chance every pick survives the ban screen: product of (1 - ban). weight 1

The product over the six of (1 - ban rate): the chance the whole comp
is playable after bans. Six ten-percent picks lose the full plan nearly
half the time; the product makes that visible where the individual rates
hide it.

#### Prefer what is winning right now (`meta-strength`, meta)

`maximize team.win_mean` - mean all-ranks win rate. weight 1

Mean all-ranks win rate across every map at the latest snapshot. A
weak prior next to the map figure, but it is what breaks ties when the
map is unknown or a hero's map sample is thin - and it carries the
snapshot's vintage, so read the WARNING fact when patches shipped since.

#### Five different jobs (`subrole-diversity`, shape)

`maximize team.subrole_diversity` - distinct subroles / size (1.0 = every pick a different job). weight 0.75

Distinct subroles divided by picks. Two flankers or two survivors
overlap jobs even when the role counts look fine; a comp whose every
pick brings a different job covers more situations with the same six
slots.

#### Bring sustained healing (`healing-floor`, sustain)

`maximize team.hps_floor` - summed published per-second healing figures. weight 1

The sum of each kit's best published per-second healing figure - beams,
streams, auras. The `under-healed` constraint handles the cliff (two
supports who together heal little); this heuristic rewards the slope.

#### Play heroes the playbook has seen work together (`cohesion`, synergy)

`maximize team.synergy_score` - summed synergy scores among the picks. weight 2.5

The summed scores of authored synergy pairs among the six, from
`db/data/authored/synergies.csv`. Every pair carries the author's
reasoning, so a high score is not a vibe - it is a stack of documented
interactions: nano on the dive tank, speed on the brawl core, pocket on
the flier.

Weighted just under coverage: a comp that answers everyone but has never
been played as a unit still has to invent its own plan mid-match.

#### No pick without a partner (`no-strangers`, synergy)

`minimize team.isolated_count` - picks with no authored partner on the team. weight 1

Picks with no authored synergy edge to any teammate. A great hero with
no documented partner in this comp is a solo act - sometimes fine,
always worth paying for, because under optimal play the enemy will
isolate exactly that pick.

#### Cycle cooldowns faster (`tempo`, tempo)

`minimize team.cooldown_median` - median cooldown across every ability on the team. weight 0.5

Median cooldown across every ability on the team. Short-cooldown kits
re-engage first and fight constantly; long ones make each fight
decisive. A mild preference for uptime, because under optimal play the
side that dictates fight frequency dictates the match.

#### Have a team-fight-ending button (`ult-burst`, tempo)

`maximize team.ult_damage_total` - summed max damage across the team's damage ultimates. weight 0.5

Summed maximum damage across the team's damage ultimates. The ceiling a
"we combo our ults" plan actually claims. Zero means the comp wins on
attrition only, which is a plan, but a slow one.

#### Charge ultimates faster (`ult-economy`, tempo)

`minimize team.ult_cost_mean` - mean ultimate charge cost where published. weight 0.5

Mean ultimate charge cost where the wiki publishes it. Cheaper ultimates
cycle more often; over a long fight sequence the comp with more ult
cycles gets more fight-ending buttons for the same damage dealt.

## The vocabulary

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
| `team.archetype_deviation` | picks over the map's top-style archetype role slots (0 without a map) |
| `team.pool_total` | team effective HP: sum of health + shield + armor |
| `team.pool_min` | the weakest pick's pool - focus fire finds the minimum |
| `team.weakest` (text) | who holds the smallest pool |
| `team.armor_total` | summed armor |
| `team.armor_share` | armor / pool |
| `team.shield_total` | summed recharging shields |
| `team.shield_share` | shields / pool |
| `team.squish_count` | picks at or under 250 pool |
| `team.squishies` (text) | the picks at or under 250 pool |
| `team.overhealth_total` | summed peak overhealth a kit can grant |
| `team.dps_floor` | summed published per-second damage figures (a floor: misses and healing ignored) |
| `team.dps_count` | picks whose kit publishes a per-second damage figure |
| `team.burst_max` | the biggest single damage figure on the team |
| `team.burst_hero` (text) | who holds the biggest single hit |
| `team.ult_damage_total` | summed max damage across the team's damage ultimates |
| `team.dmg_ults` | ultimates that carry a damage figure |
| `team.ult_cost_mean` | mean ultimate charge cost where published |
| `team.hitscan` | picks with a hitscan weapon or ability |
| `team.projectile` | picks whose weapons are projectile |
| `team.beam` | picks with a beam |
| `team.melee` | picks with a melee weapon |
| `team.aoe_count` | kit pieces tagged area of effect |
| `team.range_median` | median of each pick's longest published range |
| `team.range_max` | the longest range on the team |
| `team.range_min` | the shortest longest-range |
| `team.dmg_amp` | picks that amplify someone's damage |
| `team.hps_floor` | summed published per-second healing figures |
| `team.heal_peak_total` | summed peak single heal across all picks, any role |
| `team.heal_peak_supports` | summed peak single heal across the supports |
| `team.heal_peak_max` | the biggest single heal on the team |
| `team.heal_ratio` | support heal peak / the roster's two-support bench |
| `team.heal_amp` | picks that amplify healing |
| `team.antiheal` | picks with anti-heal |
| `team.cleanse` | picks with a cleanse |
| `team.invuln` | picks with an invulnerability |
| `team.lifelines` | picks carrying any healing at all |
| `team.cooldown_median` | median cooldown across every ability on the team |
| `team.cooldown_count` | cooldowns counted |
| `team.cc_count` | picks with crowd control (stun, sleep, immobilize, hinder, knockback) |
| `team.cc_tools` (text) | the crowd-control tools |
| `team.mobility_count` | picks with a movement or evasive ability |
| `team.mobility_tools` (text) | the movement tools |
| `team.flyers` | picks that fly or hover |
| `team.barrier_hp` | summed barrier health the team fields |
| `team.barrier_count` | picks with a barrier |
| `team.barrier_piercers` | picks whose kit ignores barriers |
| `team.deployables` | picks with deployables |
| `team.synergy_edges` | authored synergy pairs among the picks |
| `team.synergy_score` | summed synergy scores among the picks |
| `team.synergy_density` | synergy edges / possible pairs |
| `team.isolated_count` | picks with no authored partner on the team |
| `team.isolated` (text) | the isolated picks |
| `team.core_size` | largest connected group in the team's synergy graph |
| `team.pairs` (text) | the synergy pairs present |
| `team.win_mean` | mean all-ranks win rate |
| `team.pick_mass` | summed all-ranks pick rate |
| `team.availability` | chance every pick survives the ban screen: product of (1 - ban) |
| `team.max_ban_rate` | the highest ban rate on the team |
| `team.max_ban_hero` (text) | who carries the highest ban rate |
| `team.rank_sensitive_count` | picks whose win rate swings 6+ points across ranks |
| `team.trend_sum` | summed win-rate movement since the previous snapshot |
| `team.map_known` | 1 if a map is set |
| `team.map_win_mean` | mean win rate on the map (the all-ranks mean without a map) |
| `team.map_pick_mass` | summed pick rate on the map |
| `team.map_specialists` | picks running 2.5+ points over their own baseline here |
| `team.map_offmap` | picks running 2.5+ points under their own baseline here |
| `team.map_strategy_hits` | picks counterpick lists among their best maps here |
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
| `matchup.net_edges` | blue answer edges minus blue exposure edges |
| `matchup.coverage_share` | share of red answered by blue |
| `matchup.exposure_share` | share of blue answered by red |
| `matchup.double_covered` | red picks answered twice over |
| `matchup.dive_pressure` | red picks with a movement tool |
| `matchup.flyers` | red picks that fly |
| `matchup.barrier_need` | barrier health red fields |
| `matchup.antiheal_need` | red supports' summed peak heal |
| `matchup.ult_threat` | red's summed damage-ultimate ceiling |
| `matchup.ult_answers` | blue invulnerabilities plus cleanses |
| `matchup.style_lean_red` (text) | red's majority playstyle, else none |
| `matchup.style_lean_blue` (text) | blue's majority playstyle, else none |
| `map.known` | 1 if a map is set |
| `map.sided` | 1 if the mode has an attacking and a defending side (Escort, Hybrid) |
| `map.side` (text) | this seat's side on a sided map: attack, defense, or empty |
| `map.style_top` (text) | the playstyle the map rewards most |
| `map.style_margin` | top style score minus the runner-up |
| `map.mode` (text) | the game mode |
| `map.stages` | stage count |
| `world.heal_bench` | 2 x the median peak heal across the support roster |
| `world.roster_size` | heroes in the roster |
