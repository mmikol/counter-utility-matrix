# Data dictionary

Generated from the live schema (`python -m data.orchestrator docs`).

Every table carries two columns omitted from the lists below, because they
are on all of them: `source_id` (which source the row came from, see
`sources`) and `cao` — "current as of", when that row was read.

| domain | tables |
| --- | --- |
| **foundation** | `schema_migrations` · `sources` |
| **HEROES** | `abilities` · `ability_kinds` · `ability_modifiers` · `ability_stats` · `heroes` · `perk_ability_effects` · `perk_stats` · `perk_tiers` · `perks` · `roles` · `stat_keys` · `subroles` · `weapon_config_slots` · `weapon_configs` · `weapon_stats` · `weapons` |
| **MAPS** | `game_modes` · `map_modes` · `map_stages` · `maps` |
| **META** | `competitive_tiers` · `hero_meta` · `map_meta` · `meta_snapshots` · `patches` · `regions` · `seasons` |
| **PLAYBOOK** | `comp_archetypes` · `counters` · `heuristics` · `map_playstyle` · `map_strategy` · `playstyle` · `synergies` |
| **INFERENCE** | `outcome_picks` · `outcomes` · `recommendation_evidence` · `recommendation_picks` · `recommendations` · `strategies` |


## `abilities`

*HEROES · 288 rows · `002_heroes.sql`*

kind_id is NULL until the wiki pipeline sets it. Blizzard's markup labels neither weapons nor ultimates, and its ordering does not identify them either, so nothing is guessed at scrape time.

| column | type | null | references |
| --- | --- | --- | --- |
| `ability_id` | integer | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `kind_id` | smallint | yes | `ability_kinds.kind_id` |
| `name` | text | no |  |
| `description` | text | no |  |
| `position` | smallint | no |  |
| `keywords` | text | yes |  |

## `ability_kinds`

*HEROES · 4 rows · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `kind_id` | smallint | no |  |
| `code` | text | no |  |

## `ability_modifiers`

*HEROES · 116 rows · `002_heroes.sql`*

affects names the quantity scaled, so a query can find every effect on outgoing damage without knowing which stat it was published under. damage_dealt · damage_taken · healing_received · healing_dealt · movement_speed magnitude is a signed percentage: +50 amplifies, -45 reduces.

| column | type | null | references |
| --- | --- | --- | --- |
| `modifier_id` | integer | no |  |
| `ability_id` | integer | no | `abilities.ability_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `affects` | text | no |  |
| `applies_to` | text | yes |  |
| `magnitude` | numeric | no |  |
| `unit` | text | no |  |

## `ability_stats`

*HEROES · 2809 rows · `002_heroes.sql`*

One row per measurement, not per stat. A wiki value like "0.67 shots/s (max charge); 3.33 shots/s (min charge)" becomes two rows sharing a stat_key, separated by `condition`. Units are split into the unit on top and the unit underneath, so nothing has to parse a "/" to know what a number means. denominator_value carries the magnitude underneath - 1 for a plain rate, or the window a burst spans: "125 m/s"              -> 125,  meters  / seconds,  denominator_value 1 "1.25 shots/s"         -> 1.25, shots   / seconds,  denominator_value 1 "75 over 0.59 seconds" -> 75,   hp      / seconds,  denominator_value 0.59 "14 seconds"           -> 14,   seconds / NULL A rate is therefore always value / denominator_value per unit_denominator. value is NULL where the measurement is not numeric (shot types, "partial"). value_text and raw_value always keep the source strings, so anything the parser misreads stays recoverable.

| column | type | null | references |
| --- | --- | --- | --- |
| `ability_stat_id` | integer | no |  |
| `ability_id` | integer | no | `abilities.ability_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `value` | numeric | yes |  |
| `unit_numerator` | text | yes |  |
| `unit_denominator` | text | yes |  |
| `denominator_value` | numeric | yes |  |
| `condition` | text | yes |  |
| `value_text` | text | no |  |
| `raw_value` | text | no |  |

## `comp_archetypes`

*PLAYBOOK · 9 rows · `005_playbook.sql`*

What a composition IS, by archetype: the role shape a playstyle wants. playstyle tags heroes; this defines the comp those heroes assemble into - dive wants one engage tank, two flankers who arrive with him, two mobile supports. Authored in data/authored/archetypes.csv; the style vocabulary follows the playstyle table by convention. slots describe the standard 1-2-2 shape; Open Queue may flex them, and note says with whom.

| column | type | null | references |
| --- | --- | --- | --- |
| `style` | text | no |  |
| `role_id` | integer | no | `roles.role_id` |
| `slots` | smallint | no |  |
| `note` | text | yes |  |

## `competitive_tiers`

*META · 9 rows · `004_meta.sql`*

'all' is a real member of the tier dimension: it is the unfiltered figure the page reports, and keeping it as a row avoids a nullable dimension key. Region has no such member. Everything here is the Americas, so an "all regions" row would be a second population mixed in beside it. Bronze through Champion, plus the "All Tiers" aggregate the source reports alongside them. rank_order follows the source's own ordering.

| column | type | null | references |
| --- | --- | --- | --- |
| `tier_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |
| `rank_order` | smallint | no |  |

## `counters`

*PLAYBOOK · 450 rows · `005_playbook.sql`*

Who answers whom: one row means countered_by_id answers hero_id. The source publishes two directional columns per hero - "countered by" and "counters" - but they are one claim seen from either side: "X counters Y" IS "Y countered by X". The loader normalises both into this one direction and keeps the union, so a pairing the source lists on only one hero's row (about a third of them) still loads, and one it lists on both collapses to a single row. Beware the source's own naming: its field called `counters` is displayed as "Countered by". The loader follows the columns as labelled and explained by their tooltips, not the field names.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `countered_by_id` | integer | no | `heroes.hero_id` |

## `game_modes`

*MAPS · 5 rows · `003_maps.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `mode_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |

## `hero_meta`

*META · 530 rows · `004_meta.sql`*

Rates by region and tier. All rates are percentages as published (47.9 means 47.9%). These rows are across all maps.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_meta_id` | integer | no |  |
| `snapshot_id` | integer | no | `meta_snapshots.snapshot_id` |
| `hero_id` | integer | no | `heroes.hero_id` |
| `region_id` | integer | no | `regions.region_id` |
| `tier_id` | integer | no | `competitive_tiers.tier_id` |
| `win_rate` | numeric | yes |  |
| `pick_rate` | numeric | yes |  |
| `ban_rate` | numeric | yes |  |

## `heroes`

*HEROES · 53 rows · `002_heroes.sql`*

The composite foreign key makes it impossible to pair a hero with a subrole belonging to a different role than the hero's own. health, shield and armor are the hero's own pool, all in hp. Blizzard publishes none of them, so the wiki pipeline fills them in; a hero with no shield or armor leaves those NULL rather than storing a zero the source never states.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no |  |
| `slug` | text | no |  |
| `name` | text | no |  |
| `role_id` | integer | no | `roles.role_id` |
| `subrole_id` | integer | no | `subroles.role_id` |
| `health` | smallint | yes |  |
| `shield` | smallint | yes |  |
| `armor` | smallint | yes |  |
| `portrait_url` | text | yes |  |

## `heuristics`

*PLAYBOOK · 38 rows · `007_three_layers.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `heuristic_id` | text | no |  |
| `name` | text | no |  |
| `kind` | text | no |  |
| `category` | text | no |  |
| `direction` | text | yes |  |
| `metric` | text | yes |  |
| `weight` | numeric | yes |  |
| `expression` | text | yes |  |
| `params` | text | yes |  |
| `body` | text | no |  |

## `map_meta`

*META · 1590 rows · `004_meta.sql`*

Rates per map, and per tier within a map. The source's filters compose, so a hero's rates on King's Row in Bronze are a different figure from the same hero's rates on King's Row overall - and both are published. tier_id 'all' is the unfiltered figure for that map, which keeps the dimension key non-nullable. Region is not broken out here: map x tier is already 240 requests, and map x tier x region would be 720.

| column | type | null | references |
| --- | --- | --- | --- |
| `map_meta_id` | integer | no |  |
| `snapshot_id` | integer | no | `meta_snapshots.snapshot_id` |
| `hero_id` | integer | no | `heroes.hero_id` |
| `map_id` | integer | no | `maps.map_id` |
| `tier_id` | integer | no | `competitive_tiers.tier_id` |
| `region_id` | integer | no | `regions.region_id` |
| `stage_id` | integer | yes | `map_stages.stage_id` |
| `win_rate` | numeric | yes |  |
| `pick_rate` | numeric | yes |  |
| `ban_rate` | numeric | yes |  |

## `map_modes`

*MAPS · 30 rows · `003_maps.sql`*

One row per playable combination: this table is the set of matches that can actually be drawn in Open Queue Competitive. Every map currently belongs to exactly one mode, so today this holds one row per map. It is modelled many-to-many anyway because that is what the domain allows - a map can be re-released under a second mode - and because a degenerate join here costs nothing.

| column | type | null | references |
| --- | --- | --- | --- |
| `map_id` | integer | no | `maps.map_id` |
| `mode_id` | integer | no | `game_modes.mode_id` |

## `map_playstyle`

*PLAYBOOK · 20 rows · `005_playbook.sql`*

Which playstyle suits which map: the bridge between MAPS and the playbook. map_strategy picks heroes for a map; this says what KIND of fight the map rewards, which is what a comp is built around. Authored in data/authored/map_playstyle.csv, same score scale as synergies.

| column | type | null | references |
| --- | --- | --- | --- |
| `map_id` | integer | no | `maps.map_id` |
| `style` | text | no |  |
| `score` | smallint | yes |  |
| `note` | text | yes |  |

## `map_stages`

*MAPS · 36 rows · `003_maps.sql`*

Stages within a map: King's Row's first point, Ilios' Well. Defined and deliberately empty. No source publishes per-stage rates - Blizzard's map filter lists thirty whole maps and stops - so there is nothing to load here yet. It exists so map_meta can carry a stage_id now rather than needing the column bolted on later.

| column | type | null | references |
| --- | --- | --- | --- |
| `stage_id` | integer | no |  |
| `map_id` | integer | no | `maps.map_id` |
| `position` | smallint | no |  |
| `name` | text | no |  |

## `map_strategy`

*PLAYBOOK · 159 rows · `005_playbook.sql`*

The maps a hero is strongest on, best first. The source ranks them but publishes no per-map figure, so position is the whole of what it says.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `map_id` | integer | no | `maps.map_id` |
| `position` | smallint | no |  |

## `maps`

*MAPS · 30 rows · `003_maps.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `map_id` | integer | no |  |
| `name` | text | no |  |

## `meta_snapshots`

*META · 2 rows · `004_meta.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `snapshot_id` | integer | no |  |
| `captured_at` | timestamp with time zone | no |  |
| `queue` | text | no |  |
| `platform` | text | no |  |
| `input` | text | yes |  |
| `patch_id` | integer | yes | `patches.patch_id` |
| `season_id` | integer | yes | `seasons.season_id` |

## `outcome_picks`

*INFERENCE · 0 rows · `009_outcomes.sql`*

team is 'blue', 'red' or 'ban'; position orders the picks within a team.

| column | type | null | references |
| --- | --- | --- | --- |
| `outcome_id` | integer | no | `outcomes.outcome_id` |
| `team` | text | no |  |
| `position` | smallint | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |

## `outcomes`

*INFERENCE · 0 rows · `009_outcomes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `outcome_id` | integer | no |  |
| `played_at` | timestamp with time zone | no |  |
| `rec_id` | integer | yes | `recommendations.rec_id` |
| `map_id` | integer | yes | `maps.map_id` |
| `side` | text | yes |  |
| `result` | text | no |  |
| `note` | text | yes |  |

## `patches`

*META · 371 rows · `004_meta.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `patch_id` | integer | no |  |
| `name` | text | no |  |
| `released` | date | no |  |
| `platform` | text | yes |  |
| `url` | text | yes |  |

## `perk_ability_effects`

*HEROES · 194 rows · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `perk_id` | integer | no | `perks.perk_id` |
| `ability_id` | integer | no | `abilities.ability_id` |

## `perk_stats`

*HEROES · 680 rows · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `perk_stat_id` | integer | no |  |
| `perk_id` | integer | no | `perks.perk_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `value` | numeric | yes |  |
| `unit_numerator` | text | yes |  |
| `unit_denominator` | text | yes |  |
| `denominator_value` | numeric | yes |  |
| `condition` | text | yes |  |
| `value_text` | text | no |  |
| `raw_value` | text | no |  |

## `perk_tiers`

*HEROES · 2 rows · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `tier_id` | smallint | no |  |
| `code` | text | no |  |
| `name` | text | no |  |
| `unlock_level` | smallint | no |  |

## `perks`

*HEROES · 212 rows · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `perk_id` | integer | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `tier_id` | smallint | no | `perk_tiers.tier_id` |
| `name` | text | no |  |
| `description` | text | no |  |
| `position` | smallint | no |  |

## `playstyle`

*PLAYBOOK · 89 rows · `005_playbook.sql`*

Which playstyle a hero belongs to, straight from the wiki's team composition page. The style vocabulary (dive, brawl, poke) is whatever the page says, kept as text rather than a three-row lookup table: the page is the vocabulary, and a new style there should load, not break.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `style` | text | no |  |

## `recommendation_evidence`

*INFERENCE · 17 rows · `006_inference.sql`*

The board's fact lines the decider cited, by tag (F1, F2, ...). hero_id links a citation to the specific pick it justified; NULL means it supported the comp as a whole.

| column | type | null | references |
| --- | --- | --- | --- |
| `rec_id` | integer | no | `recommendations.rec_id` |
| `tag` | text | no |  |
| `source_table` | text | no |  |
| `description` | text | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |

## `recommendation_picks`

*INFERENCE · 5 rows · `006_inference.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `rec_id` | integer | no | `recommendations.rec_id` |
| `position` | smallint | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `why` | text | no |  |

## `recommendations`

*INFERENCE · 1 rows · `006_inference.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `rec_id` | integer | no |  |
| `created_at` | timestamp with time zone | no |  |
| `request` | text | no |  |
| `map_id` | integer | yes | `maps.map_id` |
| `model` | text | no |  |
| `playstyle` | text | yes |  |
| `reasoning` | text | no |  |
| `prompt` | text | no |  |
| `response` | text | no |  |

## `regions`

*META · 1 rows · `004_meta.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `region_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |

## `roles`

*HEROES · 3 rows · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `role_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |
| `icon_url` | text | yes |  |

## `schema_migrations`

*foundation · 9 rows · `008_schema_migrations.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `filename` | text | no |  |
| `applied_at` | timestamp with time zone | no |  |

## `seasons`

*META · 20 rows · `004_meta.sql`*

The game versions the meta moves with. A win rate is true of a patch, so a snapshot records which patch was live when it was captured - that is what makes an accumulated series interpretable ("these rates predate the nerf"). Scraped from the wiki's Patches cargo table; name is the wiki's own page name, since Blizzard ships most balance patches unversioned. Seasons: the coarser delineator. A patch tweaks numbers; a season swaps the hero pool and map rotation, so a snapshot records both. Authored in data/authored/seasons.csv rather than scraped: the wiki's season pages are lore articles, and its current-era page carries no dates at all.

| column | type | null | references |
| --- | --- | --- | --- |
| `season_id` | integer | no |  |
| `name` | text | no |  |
| `started` | date | no |  |
| `note` | text | yes |  |

## `sources`

*foundation · 4 rows · `001_initial_schema.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `code` | text | no |  |
| `name` | text | no |  |
| `url` | text | no |  |

## `stat_keys`

*HEROES · 48 rows · `002_heroes.sql`*

The stat vocabulary. `unit` is the canonical unit for the stat, used when a value carries no unit of its own ("damage = 90" is 90 hp).

| column | type | null | references |
| --- | --- | --- | --- |
| `stat_key_id` | integer | no |  |
| `code` | text | no |  |
| `label` | text | no |  |
| `unit` | text | yes |  |

## `strategies`

*INFERENCE · 0 rows · `006_inference.sql`*

Free-form strategy notes, authored as markdown files in data/authored/strategies/ and loaded whole: the model conditions on the prose, so no structure is imposed on it.

| column | type | null | references |
| --- | --- | --- | --- |
| `strategy_id` | integer | no |  |
| `title` | text | no |  |
| `body` | text | no |  |

## `subroles`

*HEROES · 10 rows · `002_heroes.sql`*

The ten subroles, each belonging to exactly one role, each carrying the passive it grants (e.g. "Tactician: Store excess ultimate charge.").

| column | type | null | references |
| --- | --- | --- | --- |
| `subrole_id` | integer | no |  |
| `role_id` | integer | no | `roles.role_id` |
| `code` | text | no |  |
| `name` | text | no |  |
| `passive_description` | text | no |  |
| `icon_url` | text | yes |  |

## `synergies`

*PLAYBOOK · 41 rows · `005_playbook.sql`*

Which heroes work WITH which. Proprietary, not scraped: hand-authored in data/authored/synergies.csv. No snapshot, region or tier, because an authored judgement has no population behind it. Bidirectional, unlike counters. Synergy is a property of the PAIR: if Mei works with Tracer then Tracer works with Mei - one fact, one row. A counter is an arrow: Mei answering Tracer says nothing about the reverse. So this table stores each pair once, in canonical order (lower hero_id first, enforced below), and a query reads it from either side. score is whatever scale the author keeps consistently; note carries the reasoning, which is the part a model actually wants.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `other_id` | integer | no | `heroes.hero_id` |
| `score` | smallint | yes |  |
| `note` | text | yes |  |

## `weapon_config_slots`

*HEROES · 5 rows · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `slot_id` | smallint | no |  |
| `code` | text | no |  |

## `weapon_configs`

*HEROES · 82 rows · `002_heroes.sql`*

weapon_type lives here rather than on the weapon because it varies by config: Ana's Biotic Rifle is a projectile from the hip and hitscan in ADS.

| column | type | null | references |
| --- | --- | --- | --- |
| `config_id` | integer | no |  |
| `weapon_id` | integer | no | `weapons.weapon_id` |
| `slot_id` | smallint | no | `weapon_config_slots.slot_id` |
| `name` | text | no |  |
| `weapon_type` | text | yes |  |
| `position` | smallint | no |  |
| `keywords` | text | yes |  |

## `weapon_stats`

*HEROES · 1305 rows · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `weapon_stat_id` | integer | no |  |
| `config_id` | integer | no | `weapon_configs.config_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `value` | numeric | yes |  |
| `unit_numerator` | text | yes |  |
| `unit_denominator` | text | yes |  |
| `denominator_value` | numeric | yes |  |
| `condition` | text | yes |  |
| `value_text` | text | no |  |
| `raw_value` | text | no |  |

## `weapons`

*HEROES · 60 rows · `002_heroes.sql`*

One row per weapon. A weapon's firing modes are configs, not weapons: Ana carries one Biotic Rifle, fired from the hip or down the sights.

| column | type | null | references |
| --- | --- | --- | --- |
| `weapon_id` | integer | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `name` | text | no |  |
| `position` | smallint | no |  |
